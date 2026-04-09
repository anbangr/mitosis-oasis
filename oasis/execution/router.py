"""Task routing — create execution task assignments from approved bids."""
from __future__ import annotations

import json
import sqlite3
import uuid
from pathlib import Path
from typing import Union


def _connect(db_path: Union[str, Path]) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA foreign_keys = ON")
    conn.row_factory = sqlite3.Row
    return conn


def route_tasks(session_id: str, db_path: Union[str, Path]) -> list[dict]:
    """Create task_assignment rows from approved bids for a DEPLOYED session.

    Reads the regulatory_decision for the session, looks up each approved
    bid, and creates one task_assignment per approved bid (leaf DAG node
    per assigned agent).

    Returns a list of created task assignment dicts.

    Raises ValueError if the session is not in DEPLOYED state or has no
    regulatory decision.
    """
    conn = _connect(db_path)
    try:
        # Verify session is DEPLOYED
        row = conn.execute(
            "SELECT state FROM legislative_session WHERE session_id = ?",
            (session_id,),
        ).fetchone()
        if row is None:
            raise ValueError(f"Session not found: {session_id}")
        if row["state"] != "DEPLOYED":
            raise ValueError(
                f"Session {session_id} is in state {row['state']}; expected DEPLOYED"
            )

        # Get regulatory decision
        dec = conn.execute(
            "SELECT approved_bids FROM regulatory_decision WHERE session_id = ?",
            (session_id,),
        ).fetchone()
        if dec is None:
            raise ValueError(
                f"No regulatory decision found for session {session_id}"
            )

        approved_bid_ids = json.loads(dec["approved_bids"])
        if not approved_bid_ids:
            return []

        assignments = []
        for bid_id in approved_bid_ids:
            bid = conn.execute(
                "SELECT task_node_id, bidder_did FROM bid WHERE bid_id = ?",
                (bid_id,),
            ).fetchone()
            if bid is None:
                continue

            task_id = f"task-{uuid.uuid4().hex[:8]}"
            conn.execute(
                "INSERT INTO task_assignment "
                "(task_id, session_id, node_id, agent_did, status) "
                "VALUES (?, ?, ?, ?, 'pending')",
                (task_id, session_id, bid["task_node_id"], bid["bidder_did"]),
            )
            assignments.append({
                "task_id": task_id,
                "session_id": session_id,
                "node_id": bid["task_node_id"],
                "agent_did": bid["bidder_did"],
                "status": "pending",
            })

        conn.commit()
        return assignments
    finally:
        conn.close()


def get_agent_tasks(
    agent_did: str,
    db_path: Union[str, Path],
    *,
    status: str | None = None,
) -> list[dict]:
    """List tasks assigned to an agent, optionally filtered by status."""
    conn = _connect(db_path)
    try:
        if status is not None:
            rows = conn.execute(
                "SELECT * FROM task_assignment "
                "WHERE agent_did = ? AND status = ? ORDER BY created_at",
                (agent_did, status),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM task_assignment "
                "WHERE agent_did = ? ORDER BY created_at",
                (agent_did,),
            ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_session_tasks(
    session_id: str,
    db_path: Union[str, Path],
) -> list[dict]:
    """List all tasks for a deployed session."""
    conn = _connect(db_path)
    try:
        rows = conn.execute(
            "SELECT * FROM task_assignment "
            "WHERE session_id = ? ORDER BY created_at",
            (session_id,),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()
