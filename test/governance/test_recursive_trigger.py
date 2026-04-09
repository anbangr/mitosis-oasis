"""P9 tests — trigger_child_session basics."""
from __future__ import annotations

import json
import sqlite3

import pytest

from oasis.governance.dag import (
    LeafNodeError,
    trigger_child_session,
)
from oasis.governance.schema import (
    create_governance_tables,
    seed_clerks,
    seed_constitution,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _setup_parent_session(db_path, *, session_id="parent-1"):
    """Create a parent session with a 3-node DAG (root -> A, root -> B)."""
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA foreign_keys = ON")
    # Session
    conn.execute(
        "INSERT INTO legislative_session (session_id, state, epoch) "
        "VALUES (?, 'DEPLOYED', 0)",
        (session_id,),
    )
    # Proposal
    dag_spec = json.dumps({"nodes": ["root", "A", "B"], "edges": [["root", "A"], ["root", "B"]]})
    conn.execute(
        "INSERT INTO proposal "
        "(proposal_id, session_id, proposer_did, dag_spec, "
        " token_budget_total, deadline_ms) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        ("prop-1", session_id, "did:oasis:clerk-registrar", dag_spec, 1000.0, 60000),
    )
    # DAG nodes
    for nid, label, budget in [("root", "Root", 500.0), ("A", "Task A", 200.0), ("B", "Task B", 300.0)]:
        conn.execute(
            "INSERT INTO dag_node "
            "(node_id, proposal_id, label, service_id, pop_tier, "
            " token_budget, timeout_ms) "
            "VALUES (?, 'prop-1', ?, 'svc', 1, ?, 60000)",
            (nid, label, budget),
        )
    # DAG edges: root -> A, root -> B  (root is non-leaf; A, B are leaves)
    conn.execute(
        "INSERT INTO dag_edge (proposal_id, from_node_id, to_node_id) "
        "VALUES ('prop-1', 'root', 'A')"
    )
    conn.execute(
        "INSERT INTO dag_edge (proposal_id, from_node_id, to_node_id) "
        "VALUES ('prop-1', 'root', 'B')"
    )
    conn.commit()
    conn.close()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestRecursiveTrigger:
    """trigger_child_session basic behaviour."""

    def test_nonleaf_triggers_child(self, governance_db):
        """A non-leaf node can trigger a child session."""
        _setup_parent_session(governance_db)
        child_id = trigger_child_session("parent-1", "root", governance_db)
        assert child_id is not None

        conn = sqlite3.connect(str(governance_db))
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT state, parent_session_id, parent_node_id "
            "FROM legislative_session WHERE session_id = ?",
            (child_id,),
        ).fetchone()
        conn.close()

        assert row["state"] == "SESSION_INIT"
        assert row["parent_session_id"] == "parent-1"
        assert row["parent_node_id"] == "root"

    def test_leaf_does_not_trigger(self, governance_db):
        """A leaf node cannot trigger a child session."""
        _setup_parent_session(governance_db)
        with pytest.raises(LeafNodeError):
            trigger_child_session("parent-1", "A", governance_db)

    def test_parent_session_id_fk_set(self, governance_db):
        """The child session's parent_session_id FK is correctly set."""
        _setup_parent_session(governance_db)
        child_id = trigger_child_session("parent-1", "root", governance_db)

        conn = sqlite3.connect(str(governance_db))
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT parent_session_id, parent_node_id, mission_budget_cap "
            "FROM legislative_session WHERE session_id = ?",
            (child_id,),
        ).fetchone()
        conn.close()

        assert row["parent_session_id"] == "parent-1"
        assert row["parent_node_id"] == "root"
        assert row["mission_budget_cap"] == 500.0  # defaults to parent node budget
