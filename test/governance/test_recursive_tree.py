"""P9 tests — get_session_tree retrieval."""
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


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _setup_session_with_dag(db_path, session_id, parent_session_id=None,
                            parent_node_id=None, budget=1000.0):
    """Insert a session + a non-leaf DAG node."""
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
    conn.execute(
        "INSERT INTO proposal "
        "(proposal_id, session_id, proposer_did, dag_spec, "
        " token_budget_total, deadline_ms) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (prop_id, session_id, "did:oasis:clerk-registrar",
         json.dumps({}), budget, 60000),
    )
    conn.execute(
        "INSERT INTO dag_node "
        "(node_id, proposal_id, label, service_id, pop_tier, "
        " token_budget, timeout_ms) "
        "VALUES (?, ?, 'Root', 'svc', 1, ?, 60000)",
        (f"n1-{session_id}", prop_id, budget),
    )
    conn.execute(
        "INSERT INTO dag_node "
        "(node_id, proposal_id, label, service_id, pop_tier, "
        " token_budget, timeout_ms) "
        "VALUES (?, ?, 'Leaf', 'svc', 1, ?, 60000)",
        (f"n2-{session_id}", prop_id, budget / 2),
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

class TestRecursiveTree:
    """get_session_tree retrieval."""

    def test_tree_retrieval_correct(self, governance_db):
        """A simple parent-child tree is correctly retrieved."""
        _setup_session_with_dag(governance_db, "root-s")
        child_id = trigger_child_session(
            "root-s", f"n1-root-s", governance_db
        )

        tree = get_session_tree("root-s", governance_db)

        assert tree["session_id"] == "root-s"
        assert tree["parent_session_id"] is None
        assert len(tree["children"]) == 1
        assert tree["children"][0]["session_id"] == child_id
        assert tree["children"][0]["parent_session_id"] == "root-s"
        assert tree["children"][0]["children"] == []

    def test_complex_tree_multiple_children(self, governance_db):
        """A tree with multiple children and a grandchild."""
        _setup_session_with_dag(governance_db, "root-s", budget=1000.0)

        # Two children of root
        child1 = trigger_child_session(
            "root-s", f"n1-root-s", governance_db, child_budget=400.0
        )
        child2 = trigger_child_session(
            "root-s", f"n1-root-s", governance_db, child_budget=400.0
        )

        # Add a DAG to child1 so it can have a grandchild
        _setup_session_with_dag(
            governance_db, child1,
            parent_session_id="root-s",
            parent_node_id=f"n1-root-s",
            budget=400.0,
        )

        grandchild = trigger_child_session(
            child1, f"n1-{child1}", governance_db, child_budget=200.0
        )

        tree = get_session_tree("root-s", governance_db)

        assert tree["session_id"] == "root-s"
        assert len(tree["children"]) == 2

        # Find child1 in the tree
        child1_tree = next(
            c for c in tree["children"] if c["session_id"] == child1
        )
        assert len(child1_tree["children"]) == 1
        assert child1_tree["children"][0]["session_id"] == grandchild

        # child2 has no children
        child2_tree = next(
            c for c in tree["children"] if c["session_id"] == child2
        )
        assert child2_tree["children"] == []
