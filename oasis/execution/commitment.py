"""Stake commitment — lock/unlock agent stakes for task execution."""
from __future__ import annotations

import sqlite3
import uuid
from pathlib import Path
from typing import Union


def _connect(db_path: Union[str, Path]) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA foreign_keys = ON")
    conn.row_factory = sqlite3.Row
    return conn


def _ensure_balance(conn: sqlite3.Connection, agent_did: str) -> None:
    """Create a default agent_balance row if one does not exist."""
    conn.execute(
        "INSERT OR IGNORE INTO agent_balance "
        "(agent_did, total_balance, locked_stake, available_balance) "
        "VALUES (?, 100.0, 0.0, 100.0)",
        (agent_did,),
    )


def commit_to_task(
    task_id: str,
    agent_did: str,
    db_path: Union[str, Path],
) -> dict:
    """Validate agent is assignee, lock stake, create commitment record.

    Transitions task status from 'pending' to 'committed'.

    Returns the commitment record dict.

    Raises ValueError on validation failures.
    """
    conn = _connect(db_path)
    try:
        # 1. Validate task exists and is pending
        task = conn.execute(
            "SELECT * FROM task_assignment WHERE task_id = ?",
            (task_id,),
        ).fetchone()
        if task is None:
            raise ValueError(f"Task not found: {task_id}")
        if task["status"] != "pending":
            raise ValueError(
                f"Task {task_id} is in state '{task['status']}'; expected 'pending'"
            )

        # 2. Validate agent is the assignee
        if task["agent_did"] != agent_did:
            raise ValueError(
                f"Agent {agent_did} is not assigned to task {task_id}"
            )

        # 3. Validate agent is active
        agent = conn.execute(
            "SELECT active FROM agent_registry WHERE agent_did = ?",
            (agent_did,),
        ).fetchone()
        if agent is None:
            raise ValueError(f"Agent not found: {agent_did}")
        if not agent["active"]:
            raise ValueError(f"Agent {agent_did} is not active")

        # 4. Look up stake amount from the bid
        bid = conn.execute(
            "SELECT stake_amount FROM bid "
            "WHERE session_id = ? AND task_node_id = ? AND bidder_did = ? "
            "AND status = 'approved'",
            (task["session_id"], task["node_id"], agent_did),
        ).fetchone()
        stake_amount = bid["stake_amount"] if bid else 0.5  # default

        # 5. Ensure balance row exists and check available balance
        _ensure_balance(conn, agent_did)
        bal = conn.execute(
            "SELECT available_balance FROM agent_balance WHERE agent_did = ?",
            (agent_did,),
        ).fetchone()
        if bal["available_balance"] < stake_amount:
            raise ValueError(
                f"Insufficient balance for {agent_did}: "
                f"available={bal['available_balance']}, required={stake_amount}"
            )

        # 6. Lock stake
        conn.execute(
            "UPDATE agent_balance "
            "SET locked_stake = locked_stake + ?, "
            "    available_balance = available_balance - ? "
            "WHERE agent_did = ?",
            (stake_amount, stake_amount, agent_did),
        )

        # 7. Create commitment record
        commitment_id = f"commit-{uuid.uuid4().hex[:8]}"
        conn.execute(
            "INSERT INTO task_commitment "
            "(commitment_id, task_id, agent_did, stake_amount) "
            "VALUES (?, ?, ?, ?)",
            (commitment_id, task_id, agent_did, stake_amount),
        )

        # 8. Transition task status
        conn.execute(
            "UPDATE task_assignment SET status = 'committed' WHERE task_id = ?",
            (task_id,),
        )

        conn.commit()
        return {
            "commitment_id": commitment_id,
            "task_id": task_id,
            "agent_did": agent_did,
            "stake_amount": stake_amount,
            "status": "committed",
        }
    finally:
        conn.close()


def validate_commitment(task_id: str, db_path: Union[str, Path]) -> dict:
    """Check that a commitment is valid: stake sufficient, agent active, correct state.

    Returns a dict with ``valid: bool`` and ``errors: list[str]``.
    """
    conn = _connect(db_path)
    try:
        errors: list[str] = []

        task = conn.execute(
            "SELECT * FROM task_assignment WHERE task_id = ?",
            (task_id,),
        ).fetchone()
        if task is None:
            return {"valid": False, "errors": [f"Task not found: {task_id}"]}

        if task["status"] != "committed":
            errors.append(f"Task status is '{task['status']}', expected 'committed'")

        commitment = conn.execute(
            "SELECT * FROM task_commitment WHERE task_id = ?",
            (task_id,),
        ).fetchone()
        if commitment is None:
            errors.append("No commitment record found")
        else:
            agent = conn.execute(
                "SELECT active FROM agent_registry WHERE agent_did = ?",
                (commitment["agent_did"],),
            ).fetchone()
            if agent is None:
                errors.append(f"Agent not found: {commitment['agent_did']}")
            elif not agent["active"]:
                errors.append(f"Agent {commitment['agent_did']} is not active")

            bal = conn.execute(
                "SELECT locked_stake FROM agent_balance WHERE agent_did = ?",
                (commitment["agent_did"],),
            ).fetchone()
            if bal is None:
                errors.append("No balance record found")
            elif bal["locked_stake"] < commitment["stake_amount"]:
                errors.append("Locked stake insufficient for commitment")

        return {"valid": len(errors) == 0, "errors": errors}
    finally:
        conn.close()


def release_stake(task_id: str, db_path: Union[str, Path]) -> dict:
    """Unlock stake after settlement.

    Returns a dict with the released amount.

    Raises ValueError if no commitment exists or stake already released.
    """
    conn = _connect(db_path)
    try:
        commitment = conn.execute(
            "SELECT * FROM task_commitment WHERE task_id = ?",
            (task_id,),
        ).fetchone()
        if commitment is None:
            raise ValueError(f"No commitment found for task {task_id}")

        agent_did = commitment["agent_did"]
        stake_amount = commitment["stake_amount"]

        # Check that stake is actually locked
        bal = conn.execute(
            "SELECT locked_stake FROM agent_balance WHERE agent_did = ?",
            (agent_did,),
        ).fetchone()
        if bal is None or bal["locked_stake"] < stake_amount:
            raise ValueError(
                f"Stake already released or insufficient locked balance for {agent_did}"
            )

        # Unlock stake
        conn.execute(
            "UPDATE agent_balance "
            "SET locked_stake = locked_stake - ?, "
            "    available_balance = available_balance + ? "
            "WHERE agent_did = ?",
            (stake_amount, stake_amount, agent_did),
        )

        conn.commit()
        return {
            "task_id": task_id,
            "agent_did": agent_did,
            "released_amount": stake_amount,
        }
    finally:
        conn.close()
