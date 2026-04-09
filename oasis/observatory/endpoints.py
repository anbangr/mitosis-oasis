"""Observatory REST endpoints — summary, leaderboard, timeseries, events, heatmap.

Provides FastAPI routes for real-time observability:
- Aggregate summary across all branches
- Agent leaderboard (reputation, balance, tasks)
- Reputation and treasury timeseries
- Paginated event log
- Session timeline for Gantt rendering
- Execution heatmap (agent x task status matrix)
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Union

from fastapi import APIRouter, HTTPException, Query

from oasis.observatory.schema import create_observatory_tables

# ---------------------------------------------------------------------------
# Module-level state
# ---------------------------------------------------------------------------

_db_path: str | None = None


def init_observatory_db(db_path: str) -> None:
    """Set the observatory database path and ensure tables exist."""
    global _db_path
    _db_path = db_path
    create_observatory_tables(db_path)


def _get_db() -> str:
    if _db_path is None:
        raise HTTPException(503, "Observatory database not initialised")
    return _db_path


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(_get_db())
    conn.execute("PRAGMA foreign_keys = ON")
    conn.row_factory = sqlite3.Row
    return conn


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------

router = APIRouter(prefix="/api/observatory", tags=["Observatory"])


# ========================= Summary ==========================================

@router.get("/summary")
async def get_summary():
    """Aggregate summary: sessions by state, agents by status, tasks, treasury, alerts."""
    conn = _connect()
    try:
        # Sessions by state
        sessions_by_state: dict[str, int] = {}
        try:
            rows = conn.execute(
                "SELECT state, COUNT(*) as cnt FROM legislative_session GROUP BY state"
            ).fetchall()
            sessions_by_state = {r["state"]: r["cnt"] for r in rows}
        except sqlite3.OperationalError:
            pass

        # Agents by type
        agents_by_type: dict[str, int] = {}
        try:
            rows = conn.execute(
                "SELECT agent_type, COUNT(*) as cnt FROM agent_registry GROUP BY agent_type"
            ).fetchall()
            agents_by_type = {r["agent_type"]: r["cnt"] for r in rows}
        except sqlite3.OperationalError:
            pass

        # Tasks in progress
        tasks_in_progress = 0
        try:
            row = conn.execute(
                "SELECT COUNT(*) as cnt FROM task_assignment "
                "WHERE status NOT IN ('settled', 'failed')"
            ).fetchone()
            tasks_in_progress = row["cnt"] if row else 0
        except sqlite3.OperationalError:
            pass

        # Treasury balance
        treasury_balance = 0.0
        try:
            row = conn.execute(
                "SELECT balance_after FROM treasury ORDER BY entry_id DESC LIMIT 1"
            ).fetchone()
            treasury_balance = row["balance_after"] if row else 0.0
        except sqlite3.OperationalError:
            pass

        # Active alerts
        active_alerts = 0
        try:
            row = conn.execute(
                "SELECT COUNT(*) as cnt FROM guardian_alert"
            ).fetchone()
            active_alerts = row["cnt"] if row else 0
        except sqlite3.OperationalError:
            pass

        return {
            "sessions_by_state": sessions_by_state,
            "agents_by_type": agents_by_type,
            "tasks_in_progress": tasks_in_progress,
            "treasury_balance": treasury_balance,
            "active_alerts": active_alerts,
        }
    finally:
        conn.close()


# ========================= Leaderboard ======================================

@router.get("/agents/leaderboard")
async def get_leaderboard(
    sort_by: str = Query("reputation_score", description="Sort metric"),
    limit: int = Query(20, ge=1, le=100),
):
    """Agent leaderboard ranked by configurable metric."""
    conn = _connect()
    try:
        allowed_sorts = {
            "reputation_score": "ar.reputation_score",
            "total_balance": "COALESCE(ab.total_balance, 0)",
            "available_balance": "COALESCE(ab.available_balance, 0)",
        }
        order_col = allowed_sorts.get(sort_by, "ar.reputation_score")

        query = (
            "SELECT ar.agent_did, ar.display_name, ar.agent_type, "
            "ar.reputation_score, "
            "COALESCE(ab.total_balance, 0) as total_balance, "
            "COALESCE(ab.available_balance, 0) as available_balance, "
            "COALESCE(ab.locked_stake, 0) as locked_stake "
            "FROM agent_registry ar "
            "LEFT JOIN agent_balance ab ON ar.agent_did = ab.agent_did "
            f"ORDER BY {order_col} DESC "
            "LIMIT ?"
        )
        rows = conn.execute(query, (limit,)).fetchall()
        return [
            {
                "rank": i + 1,
                "agent_did": r["agent_did"],
                "display_name": r["display_name"],
                "agent_type": r["agent_type"],
                "reputation_score": r["reputation_score"],
                "total_balance": r["total_balance"],
                "available_balance": r["available_balance"],
                "locked_stake": r["locked_stake"],
            }
            for i, r in enumerate(rows)
        ]
    except sqlite3.OperationalError:
        return []
    finally:
        conn.close()


# ========================= Reputation timeseries =============================

@router.get("/reputation/timeseries")
async def get_reputation_timeseries(
    agent_did: str | None = Query(None),
    since: str | None = Query(None, description="ISO timestamp lower bound"),
    until: str | None = Query(None, description="ISO timestamp upper bound"),
):
    """Reputation ledger time-series data."""
    conn = _connect()
    try:
        query = "SELECT * FROM reputation_ledger WHERE 1=1"
        params: list[str] = []

        if agent_did is not None:
            query += " AND agent_did = ?"
            params.append(agent_did)
        if since is not None:
            query += " AND created_at >= ?"
            params.append(since)
        if until is not None:
            query += " AND created_at <= ?"
            params.append(until)

        query += " ORDER BY created_at ASC"
        rows = conn.execute(query, params).fetchall()
        return [
            {
                "entry_id": r["entry_id"],
                "agent_did": r["agent_did"],
                "old_score": r["old_score"],
                "new_score": r["new_score"],
                "performance_score": r["performance_score"],
                "reason": r["reason"],
                "created_at": r["created_at"],
            }
            for r in rows
        ]
    except sqlite3.OperationalError:
        return []
    finally:
        conn.close()


# ========================= Treasury timeseries ===============================

@router.get("/treasury/timeseries")
async def get_treasury_timeseries():
    """Running balance over time from the treasury table."""
    conn = _connect()
    try:
        rows = conn.execute(
            "SELECT entry_id, entry_type, amount, balance_after, created_at "
            "FROM treasury ORDER BY entry_id ASC"
        ).fetchall()
        return [
            {
                "entry_id": r["entry_id"],
                "entry_type": r["entry_type"],
                "amount": r["amount"],
                "balance_after": r["balance_after"],
                "created_at": r["created_at"],
            }
            for r in rows
        ]
    except sqlite3.OperationalError:
        return []
    finally:
        conn.close()


# ========================= Events (paginated) ================================

@router.get("/events")
async def get_events(
    event_type: str | None = Query(None, description="Filter by event type"),
    session_id: str | None = Query(None),
    agent_did: str | None = Query(None),
    since: int = Query(0, description="Sequence number lower bound"),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
):
    """Paginated event_log query."""
    conn = _connect()
    try:
        query = "SELECT * FROM event_log WHERE sequence_number > ?"
        params: list = [since]

        if event_type is not None:
            query += " AND event_type = ?"
            params.append(event_type)
        if session_id is not None:
            query += " AND session_id = ?"
            params.append(session_id)
        if agent_did is not None:
            query += " AND agent_did = ?"
            params.append(agent_did)

        query += " ORDER BY sequence_number ASC LIMIT ? OFFSET ?"
        params.extend([limit, offset])

        rows = conn.execute(query, params).fetchall()
        return [
            {
                "event_id": r["event_id"],
                "event_type": r["event_type"],
                "timestamp": r["timestamp"],
                "session_id": r["session_id"],
                "agent_did": r["agent_did"],
                "payload": json.loads(r["payload"]) if r["payload"] else {},
                "sequence_number": r["sequence_number"],
            }
            for r in rows
        ]
    finally:
        conn.close()


# ========================= Session timeline ==================================

@router.get("/sessions/timeline")
async def get_sessions_timeline():
    """Session state history for Gantt rendering."""
    conn = _connect()
    try:
        rows = conn.execute(
            "SELECT session_id, state, created_at FROM legislative_session "
            "ORDER BY created_at ASC"
        ).fetchall()
        return [
            {
                "session_id": r["session_id"],
                "state": r["state"],
                "created_at": r["created_at"],
            }
            for r in rows
        ]
    except sqlite3.OperationalError:
        return []
    finally:
        conn.close()


# ========================= Execution heatmap =================================

@router.get("/execution/heatmap")
async def get_execution_heatmap():
    """Pivot task_assignment by agent x task — status matrix for heatmap rendering."""
    conn = _connect()
    try:
        rows = conn.execute(
            "SELECT agent_did, node_id, status FROM task_assignment "
            "ORDER BY agent_did, node_id"
        ).fetchall()

        agents: dict[str, dict[str, str]] = {}
        for r in rows:
            agent = r["agent_did"]
            if agent not in agents:
                agents[agent] = {}
            agents[agent][r["node_id"]] = r["status"]

        return {
            "agents": agents,
            "rows": [
                {"agent_did": agent, "tasks": tasks}
                for agent, tasks in agents.items()
            ],
        }
    except sqlite3.OperationalError:
        return {"agents": {}, "rows": []}
    finally:
        conn.close()
