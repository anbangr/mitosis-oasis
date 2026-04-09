"""P9 tests — budget conservation for child sessions."""
from __future__ import annotations

import json
import sqlite3

import pytest

from oasis.governance.dag import (
    BudgetConservationError,
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

def _setup_parent_session(db_path, *, session_id="parent-1", root_budget=500.0):
    """Create a parent session with root (non-leaf) -> A, B."""
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute(
        "INSERT INTO legislative_session (session_id, state, epoch) "
        "VALUES (?, 'DEPLOYED', 0)",
        (session_id,),
    )
    dag_spec = json.dumps({"nodes": ["root", "A", "B"], "edges": [["root", "A"], ["root", "B"]]})
    conn.execute(
        "INSERT INTO proposal "
        "(proposal_id, session_id, proposer_did, dag_spec, "
        " token_budget_total, deadline_ms) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        ("prop-1", session_id, "did:oasis:clerk-registrar", dag_spec, 1000.0, 60000),
    )
    for nid, label, budget in [("root", "Root", root_budget), ("A", "Task A", 200.0), ("B", "Task B", 300.0)]:
        conn.execute(
            "INSERT INTO dag_node "
            "(node_id, proposal_id, label, service_id, pop_tier, "
            " token_budget, timeout_ms) "
            "VALUES (?, 'prop-1', ?, 'svc', 1, ?, 60000)",
            (nid, label, budget),
        )
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

class TestRecursiveBudget:
    """Budget conservation enforcement."""

    def test_budget_conserved(self, governance_db):
        """Child budget defaults to parent node budget (conservation)."""
        _setup_parent_session(governance_db, root_budget=500.0)
        child_id = trigger_child_session("parent-1", "root", governance_db)

        conn = sqlite3.connect(str(governance_db))
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT mission_budget_cap FROM legislative_session "
            "WHERE session_id = ?",
            (child_id,),
        ).fetchone()
        conn.close()

        assert row["mission_budget_cap"] == 500.0

    def test_child_exceeding_parent_rejected(self, governance_db):
        """A child with budget > parent node budget is rejected."""
        _setup_parent_session(governance_db, root_budget=500.0)
        with pytest.raises(BudgetConservationError):
            trigger_child_session(
                "parent-1", "root", governance_db, child_budget=600.0
            )

    def test_multi_child_budget_split(self, governance_db):
        """Multiple children must cumulatively stay within parent budget."""
        _setup_parent_session(governance_db, root_budget=500.0)
        # First child gets 300
        trigger_child_session(
            "parent-1", "root", governance_db, child_budget=300.0
        )
        # Second child can get up to 200
        child2 = trigger_child_session(
            "parent-1", "root", governance_db, child_budget=200.0
        )
        assert child2 is not None
        # Third child asking for 1 more would exceed budget
        with pytest.raises(BudgetConservationError):
            trigger_child_session(
                "parent-1", "root", governance_db, child_budget=1.0
            )
