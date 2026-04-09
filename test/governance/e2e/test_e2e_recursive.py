"""E2E recursive decomposition — parent DEPLOYED triggers child session."""
from __future__ import annotations

import sqlite3

from oasis.governance.dag import trigger_child_session, get_session_tree
from oasis.governance.state_machine import LegislativeState

from .conftest import DEFAULT_DAG, drive_session_to_deployed


def test_recursive_parent_child_deployed(e2e_db, producers):
    """3-node DAG with 1 non-leaf → parent DEPLOYED → child DEPLOYED."""
    parent_sid = "recursive-parent"

    # Deploy the parent session
    parent = drive_session_to_deployed(e2e_db, producers, session_id=parent_sid)
    assert parent["sm"].current_state == LegislativeState.DEPLOYED

    # After _make_unique_dag, "root" becomes "{sid}-root"
    root_node_id = f"{parent_sid}-root"

    # Trigger a child session for the non-leaf root node
    child_sid = trigger_child_session(
        parent_session_id=parent["session_id"],
        parent_node_id=root_node_id,
        db_path=e2e_db,
        child_budget=500.0,
    )

    # Drive the child session to DEPLOYED using a sub-DAG
    child_dag = {
        "nodes": [
            {"node_id": "child-a", "label": "Sub-task A", "service_id": "sub-svc-a",
             "pop_tier": 1, "token_budget": 250.0, "timeout_ms": 60000},
            {"node_id": "child-b", "label": "Sub-task B", "service_id": "sub-svc-b",
             "pop_tier": 1, "token_budget": 200.0, "timeout_ms": 60000},
        ],
        "edges": [
            {"from_node_id": "child-a", "to_node_id": "child-b"},
        ],
    }

    child = drive_session_to_deployed(
        e2e_db,
        producers,
        session_id=child_sid,
        dag_spec=child_dag,
        total_budget=450.0,
        mission_budget_cap=500.0,
    )
    assert child["sm"].current_state == LegislativeState.DEPLOYED

    # Verify tree structure
    tree = get_session_tree(parent["session_id"], e2e_db)
    assert tree["state"] == "DEPLOYED"
    assert len(tree["children"]) == 1
    child_tree = tree["children"][0]
    assert child_tree["session_id"] == child_sid
    assert child_tree["state"] == "DEPLOYED"
