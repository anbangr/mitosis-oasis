"""Tests for invalid commitment scenarios — wrong agent, insufficient balance, etc."""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from oasis.execution.commitment import commit_to_task
from oasis.execution.router import route_tasks


def test_wrong_agent_rejected(execution_db: Path, deployed_session: dict) -> None:
    """An agent not assigned to the task cannot commit."""
    sid = deployed_session["session_id"]
    assignments = route_tasks(sid, execution_db)
    task = assignments[0]

    with pytest.raises(ValueError, match="not assigned"):
        commit_to_task(task["task_id"], "did:exec:producer-999", execution_db)


def test_insufficient_balance_rejected(execution_db: Path, deployed_session: dict) -> None:
    """An agent with insufficient balance cannot commit."""
    sid = deployed_session["session_id"]
    assignments = route_tasks(sid, execution_db)
    task = assignments[0]

    # Drain the agent's balance
    conn = sqlite3.connect(str(execution_db))
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute(
        "INSERT OR REPLACE INTO agent_balance "
        "(agent_did, total_balance, locked_stake, available_balance) "
        "VALUES (?, 0.0, 0.0, 0.0)",
        (task["agent_did"],),
    )
    conn.commit()
    conn.close()

    with pytest.raises(ValueError, match="Insufficient balance"):
        commit_to_task(task["task_id"], task["agent_did"], execution_db)


def test_already_committed_rejected(execution_db: Path, deployed_session: dict) -> None:
    """Cannot commit to a task that is already committed."""
    sid = deployed_session["session_id"]
    assignments = route_tasks(sid, execution_db)
    task = assignments[0]

    commit_to_task(task["task_id"], task["agent_did"], execution_db)

    with pytest.raises(ValueError, match="expected 'pending'"):
        commit_to_task(task["task_id"], task["agent_did"], execution_db)


def test_inactive_agent_rejected(execution_db: Path, deployed_session: dict) -> None:
    """An inactive agent cannot commit to a task."""
    sid = deployed_session["session_id"]
    assignments = route_tasks(sid, execution_db)
    task = assignments[0]

    # Deactivate the agent
    conn = sqlite3.connect(str(execution_db))
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute(
        "UPDATE agent_registry SET active = 0 WHERE agent_did = ?",
        (task["agent_did"],),
    )
    conn.commit()
    conn.close()

    with pytest.raises(ValueError, match="not active"):
        commit_to_task(task["task_id"], task["agent_did"], execution_db)
