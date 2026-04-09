"""P9 tests — depth tracking and max-depth enforcement."""
from __future__ import annotations

import json
import sqlite3

import pytest

from oasis.governance.dag import (
    RecursionDepthError,
    get_session_depth,
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

def _add_session_with_dag(db_path, session_id, parent_session_id=None, parent_node_id=None):
    """Insert a session + a simple non-leaf DAG node for chaining."""
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute(
        "INSERT INTO legislative_session "
        "(session_id, state, epoch, parent_session_id, parent_node_id, "
        " mission_budget_cap) "
        "VALUES (?, 'DEPLOYED', 0, ?, ?, 1000.0)",
        (session_id, parent_session_id, parent_node_id),
    )
    prop_id = f"prop-{session_id}"
    dag_spec = json.dumps({"nodes": ["n1", "n2"], "edges": [["n1", "n2"]]})
    conn.execute(
        "INSERT INTO proposal "
        "(proposal_id, session_id, proposer_did, dag_spec, "
        " token_budget_total, deadline_ms) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (prop_id, session_id, "did:oasis:clerk-registrar", dag_spec, 1000.0, 60000),
    )
    # n1 is non-leaf (has outgoing edge to n2)
    conn.execute(
        "INSERT INTO dag_node "
        "(node_id, proposal_id, label, service_id, pop_tier, "
        " token_budget, timeout_ms) "
        "VALUES (?, ?, 'Task', 'svc', 1, 1000.0, 60000)",
        (f"n1-{session_id}", prop_id),
    )
    conn.execute(
        "INSERT INTO dag_node "
        "(node_id, proposal_id, label, service_id, pop_tier, "
        " token_budget, timeout_ms) "
        "VALUES (?, ?, 'Leaf', 'svc', 1, 500.0, 60000)",
        (f"n2-{session_id}", prop_id),
    )
    conn.execute(
        "INSERT INTO dag_edge (proposal_id, from_node_id, to_node_id) "
        "VALUES (?, ?, ?)",
        (prop_id, f"n1-{session_id}", f"n2-{session_id}"),
    )
    conn.commit()
    conn.close()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestRecursiveDepth:
    """Depth tracking and max-depth enforcement."""

    def test_depth_1_ok(self, governance_db):
        """Creating a child at depth 1 (parent is root) succeeds."""
        _add_session_with_dag(governance_db, "root-session")
        child_id = trigger_child_session(
            "root-session", "n1-root-session", governance_db, max_depth=3
        )
        assert get_session_depth(child_id, governance_db) == 1

    def test_depth_2_ok(self, governance_db):
        """Creating a grandchild at depth 2 succeeds (max_depth=3)."""
        _add_session_with_dag(governance_db, "root-session")
        child_id = trigger_child_session(
            "root-session", "n1-root-session", governance_db, max_depth=3
        )
        # Add a proposal + DAG nodes to the child session (session already exists)
        conn = sqlite3.connect(str(governance_db))
        conn.execute("PRAGMA foreign_keys = ON")
        prop_id = f"prop-{child_id}"
        dag_spec = json.dumps({"nodes": ["cn1", "cn2"], "edges": [["cn1", "cn2"]]})
        conn.execute(
            "INSERT INTO proposal "
            "(proposal_id, session_id, proposer_did, dag_spec, "
            " token_budget_total, deadline_ms) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (prop_id, child_id, "did:oasis:clerk-registrar", dag_spec, 500.0, 60000),
        )
        conn.execute(
            "INSERT INTO dag_node "
            "(node_id, proposal_id, label, service_id, pop_tier, "
            " token_budget, timeout_ms) "
            "VALUES (?, ?, 'Task', 'svc', 1, 500.0, 60000)",
            (f"cn1-{child_id}", prop_id),
        )
        conn.execute(
            "INSERT INTO dag_node "
            "(node_id, proposal_id, label, service_id, pop_tier, "
            " token_budget, timeout_ms) "
            "VALUES (?, ?, 'Leaf', 'svc', 1, 250.0, 60000)",
            (f"cn2-{child_id}", prop_id),
        )
        conn.execute(
            "INSERT INTO dag_edge (proposal_id, from_node_id, to_node_id) "
            "VALUES (?, ?, ?)",
            (prop_id, f"cn1-{child_id}", f"cn2-{child_id}"),
        )
        conn.commit()
        conn.close()

        grandchild_id = trigger_child_session(
            child_id, f"cn1-{child_id}", governance_db, max_depth=3
        )
        assert get_session_depth(grandchild_id, governance_db) == 2

    def test_max_depth_exceeded_rejected(self, governance_db):
        """Exceeding max_depth raises RecursionDepthError."""
        _add_session_with_dag(governance_db, "root-session")
        # max_depth=1 means only root (depth 0) is allowed, no children
        with pytest.raises(RecursionDepthError):
            trigger_child_session(
                "root-session", "n1-root-session", governance_db,
                max_depth=1,
            )
