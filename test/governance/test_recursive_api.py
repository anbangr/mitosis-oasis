"""P9 tests — API-level recursive decomposition tests.

Since governance endpoints are stubs (P8 not yet implemented), these tests
exercise recursive decomposition at the module level, verifying that the
functions can be called programmatically in a flow that mimics API usage.
"""
from __future__ import annotations

import json
import sqlite3

import pytest

from oasis.governance.dag import (
    get_session_tree,
    trigger_child_session,
)
from oasis.governance.schema import (
    create_governance_tables,
    seed_clerks,
    seed_constitution,
)
from oasis.governance.state_machine import (
    LegislativeState,
    LegislativeStateMachine,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _create_full_session(db_path, session_id, parent_session_id=None,
                         parent_node_id=None, budget=1000.0):
    """Create a session with a non-leaf DAG and advance it to DEPLOYED."""
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA foreign_keys = ON")

    # Only insert if session doesn't already exist
    existing = conn.execute(
        "SELECT session_id FROM legislative_session WHERE session_id = ?",
        (session_id,),
    ).fetchone()
    if existing is None:
        conn.execute(
            "INSERT INTO legislative_session "
            "(session_id, state, epoch, parent_session_id, parent_node_id, "
            " mission_budget_cap) "
            "VALUES (?, 'DEPLOYED', 0, ?, ?, ?)",
            (session_id, parent_session_id, parent_node_id, budget),
        )

    prop_id = f"prop-{session_id}"
    dag_spec = json.dumps({"nodes": ["root", "task"], "edges": [["root", "task"]]})
    conn.execute(
        "INSERT INTO proposal "
        "(proposal_id, session_id, proposer_did, dag_spec, "
        " token_budget_total, deadline_ms) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (prop_id, session_id, "did:oasis:clerk-registrar", dag_spec, budget, 60000),
    )
    conn.execute(
        "INSERT INTO dag_node "
        "(node_id, proposal_id, label, service_id, pop_tier, "
        " token_budget, timeout_ms) "
        "VALUES (?, ?, 'Coordinator', 'svc', 1, ?, 60000)",
        (f"root-{session_id}", prop_id, budget),
    )
    conn.execute(
        "INSERT INTO dag_node "
        "(node_id, proposal_id, label, service_id, pop_tier, "
        " token_budget, timeout_ms) "
        "VALUES (?, ?, 'Worker', 'svc', 1, ?, 60000)",
        (f"task-{session_id}", prop_id, budget / 2),
    )
    conn.execute(
        "INSERT INTO dag_edge (proposal_id, from_node_id, to_node_id) "
        "VALUES (?, ?, ?)",
        (prop_id, f"root-{session_id}", f"task-{session_id}"),
    )
    conn.commit()
    conn.close()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestRecursiveAPI:
    """Module-level API tests for recursive decomposition."""

    def test_api_triggers_child_session_on_deploy(self, governance_db):
        """Simulate: parent session deploys → triggers child on a non-leaf node."""
        _create_full_session(governance_db, "api-parent-1")

        # Trigger child session (what an API endpoint would do on DEPLOYED)
        child_id = trigger_child_session(
            "api-parent-1", "root-api-parent-1", governance_db
        )

        # Verify child exists and is in SESSION_INIT
        conn = sqlite3.connect(str(governance_db))
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT state, parent_session_id, parent_node_id, "
            "       mission_budget_cap "
            "FROM legislative_session WHERE session_id = ?",
            (child_id,),
        ).fetchone()
        conn.close()

        assert row is not None
        assert row["state"] == "SESSION_INIT"
        assert row["parent_session_id"] == "api-parent-1"
        assert row["parent_node_id"] == "root-api-parent-1"
        assert row["mission_budget_cap"] == 1000.0

    def test_child_session_accessible_via_tree(self, governance_db):
        """Child session is accessible via get_session_tree after creation."""
        _create_full_session(governance_db, "api-parent-2")
        child_id = trigger_child_session(
            "api-parent-2", "root-api-parent-2", governance_db,
            child_budget=500.0,
        )

        tree = get_session_tree("api-parent-2", governance_db)

        assert tree["session_id"] == "api-parent-2"
        assert len(tree["children"]) == 1
        child = tree["children"][0]
        assert child["session_id"] == child_id
        assert child["mission_budget_cap"] == 500.0
        assert child["state"] == "SESSION_INIT"

        # The child session can be used with the state machine
        sm = LegislativeStateMachine(child_id, governance_db)
        assert sm.current_state == LegislativeState.SESSION_INIT
