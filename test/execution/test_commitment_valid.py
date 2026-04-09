"""Tests for valid commitment flow — stake lock, status transition, record creation."""
from __future__ import annotations

import sqlite3
from pathlib import Path

from oasis.execution.commitment import commit_to_task
from oasis.execution.router import route_tasks


def test_stake_locked(execution_db: Path, deployed_session: dict) -> None:
    """Committing to a task locks the stake in agent_balance."""
    sid = deployed_session["session_id"]
    assignments = route_tasks(sid, execution_db)
    task = assignments[0]

    result = commit_to_task(task["task_id"], task["agent_did"], execution_db)

    conn = sqlite3.connect(str(execution_db))
    conn.row_factory = sqlite3.Row
    bal = conn.execute(
        "SELECT * FROM agent_balance WHERE agent_did = ?",
        (task["agent_did"],),
    ).fetchone()
    conn.close()

    assert bal["locked_stake"] > 0
    assert bal["available_balance"] < 100.0
    assert result["stake_amount"] > 0


def test_status_transitions_to_committed(execution_db: Path, deployed_session: dict) -> None:
    """After commit_to_task, task status changes from 'pending' to 'committed'."""
    sid = deployed_session["session_id"]
    assignments = route_tasks(sid, execution_db)
    task = assignments[0]

    commit_to_task(task["task_id"], task["agent_did"], execution_db)

    conn = sqlite3.connect(str(execution_db))
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        "SELECT status FROM task_assignment WHERE task_id = ?",
        (task["task_id"],),
    ).fetchone()
    conn.close()

    assert row["status"] == "committed"


def test_commitment_record_created(execution_db: Path, deployed_session: dict) -> None:
    """A task_commitment record is created after committing."""
    sid = deployed_session["session_id"]
    assignments = route_tasks(sid, execution_db)
    task = assignments[0]

    result = commit_to_task(task["task_id"], task["agent_did"], execution_db)

    conn = sqlite3.connect(str(execution_db))
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        "SELECT * FROM task_commitment WHERE commitment_id = ?",
        (result["commitment_id"],),
    ).fetchone()
    conn.close()

    assert row is not None
    assert row["task_id"] == task["task_id"]
    assert row["agent_did"] == task["agent_did"]
    assert row["stake_amount"] > 0
