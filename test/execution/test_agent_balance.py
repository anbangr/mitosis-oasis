"""Tests for agent_balance — initial balance, lock, unlock, negative prevention."""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from oasis.execution.commitment import commit_to_task, release_stake
from oasis.execution.router import route_tasks


def test_initial_balance(execution_db: Path, deployed_session: dict) -> None:
    """Agents get an initial balance of 100.0 on first commitment."""
    sid = deployed_session["session_id"]
    assignments = route_tasks(sid, execution_db)
    task = assignments[0]
    agent_did = task["agent_did"]

    # Before any commitment, no balance row should exist
    conn = sqlite3.connect(str(execution_db))
    conn.row_factory = sqlite3.Row
    before = conn.execute(
        "SELECT * FROM agent_balance WHERE agent_did = ?", (agent_did,)
    ).fetchone()
    conn.close()
    assert before is None

    # Commit creates the balance row
    commit_to_task(task["task_id"], agent_did, execution_db)

    conn = sqlite3.connect(str(execution_db))
    conn.row_factory = sqlite3.Row
    after = conn.execute(
        "SELECT * FROM agent_balance WHERE agent_did = ?", (agent_did,)
    ).fetchone()
    conn.close()
    assert after is not None
    assert after["total_balance"] == 100.0


def test_lock_reduces_available(execution_db: Path, deployed_session: dict) -> None:
    """Locking stake reduces available_balance."""
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

    assert bal["locked_stake"] == result["stake_amount"]
    assert bal["available_balance"] == 100.0 - result["stake_amount"]


def test_unlock_restores(execution_db: Path, deployed_session: dict) -> None:
    """Releasing stake restores available_balance."""
    sid = deployed_session["session_id"]
    assignments = route_tasks(sid, execution_db)
    task = assignments[0]

    commit_to_task(task["task_id"], task["agent_did"], execution_db)
    release_stake(task["task_id"], execution_db)

    conn = sqlite3.connect(str(execution_db))
    conn.row_factory = sqlite3.Row
    bal = conn.execute(
        "SELECT * FROM agent_balance WHERE agent_did = ?",
        (task["agent_did"],),
    ).fetchone()
    conn.close()

    assert bal["locked_stake"] == 0.0
    assert bal["available_balance"] == 100.0


def test_negative_balance_prevented(execution_db: Path, deployed_session: dict) -> None:
    """Cannot lock stake exceeding available balance."""
    sid = deployed_session["session_id"]
    assignments = route_tasks(sid, execution_db)
    task = assignments[0]

    # Set available balance to 0
    conn = sqlite3.connect(str(execution_db))
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute(
        "INSERT OR REPLACE INTO agent_balance "
        "(agent_did, total_balance, locked_stake, available_balance) "
        "VALUES (?, 100.0, 100.0, 0.0)",
        (task["agent_did"],),
    )
    conn.commit()
    conn.close()

    with pytest.raises(ValueError, match="Insufficient balance"):
        commit_to_task(task["task_id"], task["agent_did"], execution_db)
