"""Tests for stake release — after settlement, double-release prevention."""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from oasis.execution.commitment import commit_to_task, release_stake
from oasis.execution.router import route_tasks


def test_stake_released_after_settlement(execution_db: Path, deployed_session: dict) -> None:
    """After release_stake, the locked stake is returned to available balance."""
    sid = deployed_session["session_id"]
    assignments = route_tasks(sid, execution_db)
    task = assignments[0]

    commit_result = commit_to_task(task["task_id"], task["agent_did"], execution_db)
    stake_amount = commit_result["stake_amount"]

    # Check balance before release
    conn = sqlite3.connect(str(execution_db))
    conn.row_factory = sqlite3.Row
    before = conn.execute(
        "SELECT * FROM agent_balance WHERE agent_did = ?",
        (task["agent_did"],),
    ).fetchone()
    conn.close()

    assert before["locked_stake"] >= stake_amount

    # Release
    release_result = release_stake(task["task_id"], execution_db)
    assert release_result["released_amount"] == stake_amount

    # Check balance after release
    conn = sqlite3.connect(str(execution_db))
    conn.row_factory = sqlite3.Row
    after = conn.execute(
        "SELECT * FROM agent_balance WHERE agent_did = ?",
        (task["agent_did"],),
    ).fetchone()
    conn.close()

    assert after["locked_stake"] == before["locked_stake"] - stake_amount
    assert after["available_balance"] == before["available_balance"] + stake_amount


def test_double_release_prevented(execution_db: Path, deployed_session: dict) -> None:
    """Releasing stake twice for the same task raises an error."""
    sid = deployed_session["session_id"]
    assignments = route_tasks(sid, execution_db)
    task = assignments[0]

    commit_to_task(task["task_id"], task["agent_did"], execution_db)
    release_stake(task["task_id"], execution_db)

    with pytest.raises(ValueError, match="already released|insufficient"):
        release_stake(task["task_id"], execution_db)
