"""DAG specification, validation, and topological sorting.

Implements the task-DAG data model from the AgentCity paper (SS3.5):
- DAGSpec / DAGNode / DAGEdge dataclasses
- Acyclicity verification via topological sort (Kahn's algorithm)
- Structural validation (roots, terminals, orphans, budgets, I/O schemas)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set


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
