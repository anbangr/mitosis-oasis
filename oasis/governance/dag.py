"""DAG specification, validation, and topological sorting.

Implements the task-DAG data model from the AgentCity paper (SS3.5):
- DAGSpec / DAGNode / DAGEdge dataclasses
- Acyclicity verification via topological sort (Kahn's algorithm)
- Structural validation (roots, terminals, orphans, budgets, I/O schemas)
- Recursive decomposition: child sessions, budget conservation, depth tracking
"""
from __future__ import annotations

import sqlite3
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Union


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class CycleError(Exception):
    """Raised when a cycle is detected in the DAG."""


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------

@dataclass
class DAGNode:
    """A single task node in the DAG."""
    node_id: str
    label: str
    service_id: str
    input_schema: Optional[dict] = None
    output_schema: Optional[dict] = None
    pop_tier: int = 1
    redundancy_factor: int = 1
    consensus_threshold: int = 1
    token_budget: float = 0.0
    timeout_ms: int = 60000
    risk_tier: str = "low"


@dataclass
class DAGEdge:
    """A directed edge between two DAG nodes."""
    from_node_id: str
    to_node_id: str
    data_flow_schema: Optional[dict] = None


@dataclass
class DAGSpec:
    """Full DAG specification: nodes + edges."""
    nodes: List[DAGNode] = field(default_factory=list)
    edges: List[DAGEdge] = field(default_factory=list)


@dataclass
class DAGValidationResult:
    """Outcome of DAG structural validation."""
    valid: bool
    errors: List[str] = field(default_factory=list)
    topological_order: List[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------

def find_roots(dag: DAGSpec) -> List[str]:
    """Return node_ids that have no incoming edges (root nodes)."""
    all_ids = {n.node_id for n in dag.nodes}
    has_incoming = {e.to_node_id for e in dag.edges}
    return [n.node_id for n in dag.nodes if n.node_id not in has_incoming]


def find_leaves(dag: DAGSpec) -> List[str]:
    """Return node_ids that have no outgoing edges (terminal/leaf nodes)."""
    has_outgoing = {e.from_node_id for e in dag.edges}
    return [n.node_id for n in dag.nodes if n.node_id not in has_outgoing]


# ---------------------------------------------------------------------------
# Topological sort (Kahn's algorithm)
# ---------------------------------------------------------------------------

def topological_sort(dag: DAGSpec) -> List[str]:
    """Return a topological ordering of node_ids.

    Raises ``CycleError`` if the DAG contains a cycle.
    """
    if not dag.nodes:
        return []

    # Build adjacency and in-degree structures
    node_ids = {n.node_id for n in dag.nodes}
    in_degree: Dict[str, int] = {nid: 0 for nid in node_ids}
    adjacency: Dict[str, List[str]] = {nid: [] for nid in node_ids}

    for edge in dag.edges:
        adjacency[edge.from_node_id].append(edge.to_node_id)
        in_degree[edge.to_node_id] += 1

    # Start with all zero-in-degree nodes (sorted for determinism)
    queue = sorted([nid for nid, deg in in_degree.items() if deg == 0])
    order: List[str] = []

    while queue:
        node = queue.pop(0)
        order.append(node)
        for neighbor in sorted(adjacency[node]):
            in_degree[neighbor] -= 1
            if in_degree[neighbor] == 0:
                queue.append(neighbor)
        queue.sort()

    if len(order) != len(node_ids):
        raise CycleError("DAG contains a cycle")

    return order


# ---------------------------------------------------------------------------
# Full DAG validation
# ---------------------------------------------------------------------------

def validate_dag(dag: DAGSpec) -> DAGValidationResult:
    """Validate a DAG specification.

    Checks:
    1. Non-empty (at least 1 node)
    2. Acyclicity (topological sort)
    3. At least 1 root node and 1 terminal node
    4. No orphan nodes (nodes not referenced by any edge in a multi-node DAG)
    5. All leaf nodes have a valid PoP tier (1-3)
    6. Budget conservation (sum of direct children budgets <= parent budget)
    7. I/O schema compatibility on edges
    """
    errors: List[str] = []

    # --- 1. Non-empty ---
    if not dag.nodes:
        return DAGValidationResult(valid=False, errors=["DAG has no nodes"])

    node_map: Dict[str, DAGNode] = {n.node_id: n for n in dag.nodes}
    node_ids: Set[str] = set(node_map.keys())

    # Validate edge references
    for edge in dag.edges:
        if edge.from_node_id not in node_ids:
            errors.append(f"Edge references unknown source node: {edge.from_node_id}")
        if edge.to_node_id not in node_ids:
            errors.append(f"Edge references unknown target node: {edge.to_node_id}")
    if errors:
        return DAGValidationResult(valid=False, errors=errors)

    # --- 2. Acyclicity ---
    try:
        topo_order = topological_sort(dag)
    except CycleError:
        errors.append("DAG contains a cycle")
        return DAGValidationResult(valid=False, errors=errors)

    # --- 3. Roots and terminals ---
    roots = find_roots(dag)
    leaves = find_leaves(dag)

    if not roots:
        errors.append("DAG has no root nodes (every node has an incoming edge)")
    if not leaves:
        errors.append("DAG has no terminal nodes (every node has an outgoing edge)")

    # --- 4. Orphan check (multi-node DAGs) ---
    if len(dag.nodes) > 1:
        connected: Set[str] = set()
        for edge in dag.edges:
            connected.add(edge.from_node_id)
            connected.add(edge.to_node_id)
        orphans = node_ids - connected
        for orphan in sorted(orphans):
            errors.append(f"Orphan node not connected by any edge: {orphan}")

    # --- 5. PoP tier validation on all nodes ---
    for node in dag.nodes:
        if node.pop_tier not in (1, 2, 3):
            errors.append(
                f"Node {node.node_id} has invalid PoP tier: {node.pop_tier} "
                f"(must be 1, 2, or 3)"
            )

    # --- 6. Budget conservation ---
    # Build children map
    children_map: Dict[str, List[str]] = {nid: [] for nid in node_ids}
    for edge in dag.edges:
        children_map[edge.from_node_id].append(edge.to_node_id)

    for parent_id, child_ids in children_map.items():
        if not child_ids:
            continue
        parent_budget = node_map[parent_id].token_budget
        child_sum = sum(node_map[cid].token_budget for cid in child_ids)
        if child_sum > parent_budget + 1e-9:  # small epsilon for float
            errors.append(
                f"Budget violation: children of {parent_id} sum to "
                f"{child_sum:.2f} but parent budget is {parent_budget:.2f}"
            )

    # --- 7. I/O schema compatibility ---
    for edge in dag.edges:
        source = node_map[edge.from_node_id]
        target = node_map[edge.to_node_id]
        if source.output_schema and target.input_schema:
            # Check that target input fields are a subset of source output fields
            source_fields = set(source.output_schema.keys())
            target_fields = set(target.input_schema.keys())
            missing = target_fields - source_fields
            if missing:
                errors.append(
                    f"I/O schema mismatch on edge {edge.from_node_id} -> "
                    f"{edge.to_node_id}: target requires fields {missing} "
                    f"not in source output"
                )

    # Zero budget check
    for node in dag.nodes:
        if node.token_budget <= 0:
            errors.append(
                f"Node {node.node_id} has non-positive budget: "
                f"{node.token_budget}"
            )

    return DAGValidationResult(
        valid=len(errors) == 0,
        errors=errors,
        topological_order=topo_order if not errors else [],
    )


# ---------------------------------------------------------------------------
# Recursive decomposition exceptions
# ---------------------------------------------------------------------------

class RecursionDepthError(Exception):
    """Raised when recursive child session creation exceeds max depth."""


class BudgetConservationError(Exception):
    """Raised when child session budget exceeds parent node budget."""


class LeafNodeError(Exception):
    """Raised when attempting to trigger a child session on a leaf node."""


# ---------------------------------------------------------------------------
# Recursive decomposition helpers
# ---------------------------------------------------------------------------

DEFAULT_MAX_DEPTH = 3


def _connect(db_path: Union[str, Path]) -> sqlite3.Connection:
    """Open a connection with foreign keys enabled."""
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA foreign_keys = ON")
    conn.row_factory = sqlite3.Row
    return conn


def get_session_depth(session_id: str, db_path: Union[str, Path]) -> int:
    """Return the depth of a session by traversing the parent_session_id chain.

    A root session (no parent) has depth 0.
    """
    conn = _connect(db_path)
    try:
        depth = 0
        current = session_id
        while True:
            row = conn.execute(
                "SELECT parent_session_id FROM legislative_session "
                "WHERE session_id = ?",
                (current,),
            ).fetchone()
            if row is None:
                raise ValueError(f"Session {current} not found")
            parent = row["parent_session_id"]
            if parent is None:
                return depth
            depth += 1
            current = parent
    finally:
        conn.close()


def _is_leaf_node(node_id: str, proposal_id: str,
                  conn: sqlite3.Connection) -> bool:
    """Check whether a DAG node is a leaf (no outgoing edges)."""
    row = conn.execute(
        "SELECT COUNT(*) AS cnt FROM dag_edge "
        "WHERE proposal_id = ? AND from_node_id = ?",
        (proposal_id, node_id),
    ).fetchone()
    return row["cnt"] == 0


def _get_node_budget(node_id: str, conn: sqlite3.Connection) -> float:
    """Return the token_budget of a DAG node."""
    row = conn.execute(
        "SELECT token_budget FROM dag_node WHERE node_id = ?",
        (node_id,),
    ).fetchone()
    if row is None:
        raise ValueError(f"DAG node {node_id} not found")
    return float(row["token_budget"])


def _get_proposal_for_node(node_id: str,
                           conn: sqlite3.Connection) -> str:
    """Return the proposal_id that owns a given DAG node."""
    row = conn.execute(
        "SELECT proposal_id FROM dag_node WHERE node_id = ?",
        (node_id,),
    ).fetchone()
    if row is None:
        raise ValueError(f"DAG node {node_id} not found")
    return row["proposal_id"]


def _sum_child_budgets(parent_session_id: str, parent_node_id: str,
                       conn: sqlite3.Connection) -> float:
    """Sum the mission_budget_cap of all existing children of a parent node."""
    row = conn.execute(
        "SELECT COALESCE(SUM(mission_budget_cap), 0) AS total "
        "FROM legislative_session "
        "WHERE parent_session_id = ? AND parent_node_id = ?",
        (parent_session_id, parent_node_id),
    ).fetchone()
    return float(row["total"])


# ---------------------------------------------------------------------------
# Public API — recursive decomposition
# ---------------------------------------------------------------------------

def trigger_child_session(
    parent_session_id: str,
    parent_node_id: str,
    db_path: Union[str, Path],
    *,
    child_budget: Optional[float] = None,
    max_depth: int = DEFAULT_MAX_DEPTH,
) -> str:
    """Create a new legislative session linked to *parent_session_id*.

    The child session:
    - Is linked via ``parent_session_id`` and ``parent_node_id`` FKs.
    - Starts in ``SESSION_INIT`` state.
    - Inherits quorum rules from the constitution (same rules at all depths).
    - Has ``mission_budget_cap ≤ parent node's token_budget``.
    - Respects the configurable ``max_depth`` (default 3).

    Parameters
    ----------
    parent_session_id:
        The session ID of the parent session.
    parent_node_id:
        The DAG node ID in the parent session that triggers decomposition.
        Must be a non-leaf node.
    db_path:
        Path to the governance SQLite database.
    child_budget:
        Budget for the child session. Defaults to the parent node's
        ``token_budget``. Must not exceed it.
    max_depth:
        Maximum allowed session depth (default 3). Depth 0 is root.

    Returns
    -------
    str
        The session_id of the newly created child session.

    Raises
    ------
    LeafNodeError
        If *parent_node_id* is a leaf node in its proposal's DAG.
    BudgetConservationError
        If *child_budget* exceeds the parent node's token_budget or the
        cumulative child budgets exceed the parent node budget.
    RecursionDepthError
        If creating the child would exceed *max_depth*.
    """
    conn = _connect(db_path)
    try:
        # 1. Validate parent session exists
        parent_row = conn.execute(
            "SELECT session_id FROM legislative_session WHERE session_id = ?",
            (parent_session_id,),
        ).fetchone()
        if parent_row is None:
            raise ValueError(f"Parent session {parent_session_id} not found")

        # 2. Find the proposal that owns the node
        proposal_id = _get_proposal_for_node(parent_node_id, conn)

        # 3. Validate the node is NOT a leaf
        if _is_leaf_node(parent_node_id, proposal_id, conn):
            raise LeafNodeError(
                f"Node {parent_node_id} is a leaf node and cannot "
                f"trigger a child session"
            )

        # 4. Depth check
        parent_depth = get_session_depth(parent_session_id, db_path)
        child_depth = parent_depth + 1
        if child_depth >= max_depth:
            raise RecursionDepthError(
                f"Child session would be at depth {child_depth}, "
                f"exceeding max depth {max_depth}"
            )

        # 5. Budget conservation
        node_budget = _get_node_budget(parent_node_id, conn)
        if child_budget is None:
            child_budget = node_budget
        if child_budget > node_budget + 1e-9:
            raise BudgetConservationError(
                f"Child budget {child_budget} exceeds parent node "
                f"budget {node_budget}"
            )
        # Check cumulative children budgets
        existing_child_sum = _sum_child_budgets(
            parent_session_id, parent_node_id, conn
        )
        if existing_child_sum + child_budget > node_budget + 1e-9:
            raise BudgetConservationError(
                f"Cumulative child budgets ({existing_child_sum} + "
                f"{child_budget} = {existing_child_sum + child_budget}) "
                f"exceed parent node budget {node_budget}"
            )

        # 6. Create the child session
        child_session_id = f"session-{uuid.uuid4().hex[:12]}"
        conn.execute(
            "INSERT INTO legislative_session "
            "(session_id, state, epoch, parent_session_id, parent_node_id, "
            " mission_budget_cap) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                child_session_id,
                "SESSION_INIT",
                0,
                parent_session_id,
                parent_node_id,
                child_budget,
            ),
        )
        conn.commit()
        return child_session_id
    finally:
        conn.close()


def get_session_tree(
    root_session_id: str,
    db_path: Union[str, Path],
) -> Dict[str, Any]:
    """Return the full session hierarchy rooted at *root_session_id*.

    Returns a nested dict of the form::

        {
            "session_id": "...",
            "state": "...",
            "parent_session_id": None,
            "parent_node_id": None,
            "mission_budget_cap": ...,
            "children": [
                { "session_id": "...", "children": [...] },
                ...
            ],
        }
    """
    conn = _connect(db_path)
    try:
        # Fetch all sessions
        rows = conn.execute(
            "SELECT session_id, state, parent_session_id, parent_node_id, "
            "       mission_budget_cap "
            "FROM legislative_session"
        ).fetchall()

        # Build a lookup and children map
        nodes: Dict[str, Dict[str, Any]] = {}
        children_map: Dict[str, List[str]] = {}

        for row in rows:
            sid = row["session_id"]
            nodes[sid] = {
                "session_id": sid,
                "state": row["state"],
                "parent_session_id": row["parent_session_id"],
                "parent_node_id": row["parent_node_id"],
                "mission_budget_cap": row["mission_budget_cap"],
                "children": [],
            }
            parent = row["parent_session_id"]
            if parent is not None:
                children_map.setdefault(parent, []).append(sid)

        if root_session_id not in nodes:
            raise ValueError(f"Session {root_session_id} not found")

        # Build tree recursively
        def _build(sid: str) -> Dict[str, Any]:
            node = dict(nodes[sid])
            node["children"] = [
                _build(child_id)
                for child_id in sorted(children_map.get(sid, []))
            ]
            return node

        return _build(root_session_id)
    finally:
        conn.close()
