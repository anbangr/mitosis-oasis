"""Tests for basic task routing — approved bids → task assignments."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from oasis.execution.router import get_agent_tasks, get_session_tasks, route_tasks


def test_tasks_from_approved_bids(execution_db: Path, deployed_session: dict) -> None:
    """route_tasks creates task_assignment rows from approved bids."""
    sid = deployed_session["session_id"]
    assignments = route_tasks(sid, execution_db)
    assert len(assignments) > 0, "Expected at least one task assignment"

    # All assignments should be pending
    for a in assignments:
        assert a["status"] == "pending"
        assert a["session_id"] == sid


def test_one_per_leaf_node(execution_db: Path, deployed_session: dict) -> None:
    """Each leaf DAG node should have exactly one task assignment."""
    sid = deployed_session["session_id"]
    assignments = route_tasks(sid, execution_db)

    # Count number of approved bids
    conn = sqlite3.connect(str(execution_db))
    conn.row_factory = sqlite3.Row
    dec = conn.execute(
        "SELECT approved_bids FROM regulatory_decision WHERE session_id = ?",
        (sid,),
    ).fetchone()
    conn.close()

    approved = json.loads(dec["approved_bids"])
    assert len(assignments) == len(approved), (
        f"Expected {len(approved)} assignments, got {len(assignments)}"
    )


def test_correct_assignee(execution_db: Path, deployed_session: dict) -> None:
    """Each task should be assigned to the correct winning bidder."""
    sid = deployed_session["session_id"]
    assignments = route_tasks(sid, execution_db)

    conn = sqlite3.connect(str(execution_db))
    conn.row_factory = sqlite3.Row

    for a in assignments:
        # Verify agent_did matches the approved bid's bidder
        bid = conn.execute(
            "SELECT bidder_did FROM bid "
            "WHERE session_id = ? AND task_node_id = ? AND status = 'approved'",
            (sid, a["node_id"]),
        ).fetchone()
        assert bid is not None, f"No approved bid for node {a['node_id']}"
        assert a["agent_did"] == bid["bidder_did"]

    conn.close()


def test_session_linkage(execution_db: Path, deployed_session: dict) -> None:
    """get_session_tasks returns all tasks for the session."""
    sid = deployed_session["session_id"]
    route_tasks(sid, execution_db)

    tasks = get_session_tasks(sid, execution_db)
    assert len(tasks) > 0
    for t in tasks:
        assert t["session_id"] == sid
