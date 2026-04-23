"""Adjudication API endpoints — alerts, flags, decisions, balances, treasury.

Provides FastAPI routes for the adjudication branch:
- Guardian alert queries
- Coordination flag queries
- Adjudication decision queries
- Agent balance and sanction history
- Treasury summary and ledger
"""
from __future__ import annotations

import sqlite3
from typing import Any

from fastapi import APIRouter, HTTPException, Query

from oasis.config import PlatformConfig

# ---------------------------------------------------------------------------
# Module-level state
# ---------------------------------------------------------------------------

_db_path: str | None = None
_config: PlatformConfig = PlatformConfig()


def init_adjudication_db(db_path: str, config: PlatformConfig | None = None) -> None:
    """Set the adjudication database path and optional config."""
    global _db_path, _config
    _db_path = db_path
    if config is not None:
        _config = config


def _get_db() -> str:
    if _db_path is None:
        raise HTTPException(503, "Adjudication database not initialised")
    return _db_path


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(_get_db())
    conn.execute("PRAGMA foreign_keys = ON")
    conn.row_factory = sqlite3.Row
    return conn


def _ensure_agent_balance(conn: sqlite3.Connection, agent_did: str) -> None:
    try:
        conn.execute(
            "INSERT OR IGNORE INTO agent_registry "
            "(agent_did, agent_type, display_name) "
            "VALUES (?, 'producer', ?)",
            (agent_did, agent_did),
        )
    except sqlite3.OperationalError:
        # The live adjudication-only DB may not carry the full governance schema.
        pass
    conn.execute(
        "INSERT OR IGNORE INTO agent_balance "
        "(agent_did, total_balance, locked_stake, available_balance) "
        "VALUES (?, 100.0, 0.0, 100.0)",
        (agent_did,),
    )
    conn.commit()


# ---------------------------------------------------------------------------
# Shared route definitions
# ---------------------------------------------------------------------------

_routes = APIRouter(tags=["Adjudication"])

# Public router aliases
router = APIRouter(prefix="/api/adjudication", tags=["Adjudication"])
v1_router = APIRouter(prefix="/api/v1/adjudication", tags=["Adjudication"])


# ========================= Alerts ==========================================

@_routes.get("/alerts", response_model=list[dict[str, Any]])
async def list_alerts(
    severity: str | None = Query(None, description="Filter by severity"),
    agent_did: str | None = Query(None, description="Filter by agent DID"),
    task_id: str | None = Query(None, description="Filter by task ID"),
):
    """List guardian alerts with optional filters."""
    conn = _connect()
    try:
        query = "SELECT ga.* FROM guardian_alert ga"
        conditions: list[str] = []
        params: list[str] = []

        if agent_did is not None:
            query += " JOIN task_assignment ta ON ga.task_id = ta.task_id"
            conditions.append("ta.agent_did = ?")
            params.append(agent_did)

        if severity is not None:
            conditions.append("ga.severity = ?")
            params.append(severity)

        if task_id is not None:
            conditions.append("ga.task_id = ?")
            params.append(task_id)

        if conditions:
            query += " WHERE " + " AND ".join(conditions)

        query += " ORDER BY ga.created_at DESC"

        rows = conn.execute(query, params).fetchall()
        return [
            {
                "alert_id": r["alert_id"],
                "task_id": r["task_id"],
                "alert_type": r["alert_type"],
                "severity": r["severity"],
                "details": r["details"],
                "created_at": r["created_at"],
            }
            for r in rows
        ]
    finally:
        conn.close()


@_routes.get("/alerts/{alert_id}", response_model=dict[str, Any])
async def get_alert(alert_id: str):
    """Get details for a specific guardian alert."""
    conn = _connect()
    try:
        row = conn.execute(
            "SELECT * FROM guardian_alert WHERE alert_id = ?",
            (alert_id,),
        ).fetchone()
        if row is None:
            raise HTTPException(404, f"Alert not found: {alert_id}")
        return {
            "alert_id": row["alert_id"],
            "task_id": row["task_id"],
            "alert_type": row["alert_type"],
            "severity": row["severity"],
            "details": row["details"],
            "created_at": row["created_at"],
        }
    finally:
        conn.close()


# ========================= Flags ===========================================

@_routes.get("/flags", response_model=list[dict[str, Any]])
async def list_flags(
    session_id: str | None = Query(None, description="Filter by session ID"),
    agent_did: str | None = Query(None, description="Filter by agent DID"),
):
    """List coordination flags with optional filters."""
    conn = _connect()
    try:
        query = "SELECT * FROM coordination_flag"
        conditions: list[str] = []
        params: list[str] = []

        if session_id is not None:
            conditions.append("session_id = ?")
            params.append(session_id)

        if agent_did is not None:
            conditions.append("(agent_did_1 = ? OR agent_did_2 = ?)")
            params.extend([agent_did, agent_did])

        if conditions:
            query += " WHERE " + " AND ".join(conditions)

        query += " ORDER BY created_at DESC"

        rows = conn.execute(query, params).fetchall()
        return [
            {
                "flag_id": r["flag_id"],
                "session_id": r["session_id"],
                "agent_did_1": r["agent_did_1"],
                "agent_did_2": r["agent_did_2"],
                "flag_type": r["flag_type"],
                "score": r["score"],
                "created_at": r["created_at"],
            }
            for r in rows
        ]
    finally:
        conn.close()


# ========================= Decisions =======================================

@_routes.get("/decisions", response_model=list[dict[str, Any]])
async def list_decisions(
    agent_did: str | None = Query(None, description="Filter by agent DID"),
    decision_type: str | None = Query(None, description="Filter by decision type"),
):
    """List adjudication decisions with optional filters."""
    conn = _connect()
    try:
        query = "SELECT * FROM adjudication_decision"
        conditions: list[str] = []
        params: list[str] = []

        if agent_did is not None:
            conditions.append("agent_did = ?")
            params.append(agent_did)

        if decision_type is not None:
            conditions.append("decision_type = ?")
            params.append(decision_type)

        if conditions:
            query += " WHERE " + " AND ".join(conditions)

        query += " ORDER BY created_at DESC"

        rows = conn.execute(query, params).fetchall()
        return [
            {
                "decision_id": r["decision_id"],
                "alert_id": r["alert_id"],
                "flag_id": r["flag_id"],
                "agent_did": r["agent_did"],
                "decision_type": r["decision_type"],
                "severity": r["severity"],
                "reason": r["reason"],
                "layer1_result": r["layer1_result"],
                "layer2_advisory": r["layer2_advisory"],
                "created_at": r["created_at"],
            }
            for r in rows
        ]
    finally:
        conn.close()


@_routes.get("/decisions/{decision_id}", response_model=dict[str, Any])
async def get_decision(decision_id: str):
    """Get details for a specific adjudication decision."""
    conn = _connect()
    try:
        row = conn.execute(
            "SELECT * FROM adjudication_decision WHERE decision_id = ?",
            (decision_id,),
        ).fetchone()
        if row is None:
            raise HTTPException(404, f"Decision not found: {decision_id}")
        return {
            "decision_id": row["decision_id"],
            "alert_id": row["alert_id"],
            "flag_id": row["flag_id"],
            "agent_did": row["agent_did"],
            "decision_type": row["decision_type"],
            "severity": row["severity"],
            "reason": row["reason"],
            "layer1_result": row["layer1_result"],
            "layer2_advisory": row["layer2_advisory"],
            "created_at": row["created_at"],
        }
    finally:
        conn.close()


# ========================= Agent balance & sanctions ========================

@_routes.get("/agents/{agent_did}/balance", response_model=dict[str, Any])
async def get_agent_balance(agent_did: str):
    """Get agent balance details."""
    conn = _connect()
    try:
        _ensure_agent_balance(conn, agent_did)
        row = conn.execute(
            "SELECT * FROM agent_balance WHERE agent_did = ?",
            (agent_did,),
        ).fetchone()
        return {
            "agent_did": row["agent_did"],
            "total_balance": row["total_balance"],
            "locked_stake": row["locked_stake"],
            "available_balance": row["available_balance"],
        }
    finally:
        conn.close()


@_routes.get("/agents/{agent_did}/sanctions", response_model=list[dict[str, Any]])
async def get_agent_sanctions(agent_did: str):
    """Get sanction history for an agent."""
    conn = _connect()
    try:
        rows = conn.execute(
            "SELECT * FROM adjudication_decision "
            "WHERE agent_did = ? ORDER BY created_at DESC",
            (agent_did,),
        ).fetchall()
        return [
            {
                "decision_id": r["decision_id"],
                "alert_id": r["alert_id"],
                "flag_id": r["flag_id"],
                "agent_did": r["agent_did"],
                "decision_type": r["decision_type"],
                "severity": r["severity"],
                "reason": r["reason"],
                "layer1_result": r["layer1_result"],
                "layer2_advisory": r["layer2_advisory"],
                "created_at": r["created_at"],
            }
            for r in rows
        ]
    finally:
        conn.close()


# ========================= Treasury ========================================

@_routes.get("/treasury", response_model=dict[str, Any])
async def get_treasury():
    """Get treasury summary (inflows, outflows, net balance)."""
    conn = _connect()
    try:
        rows = conn.execute(
            "SELECT entry_type, SUM(amount) as total FROM treasury GROUP BY entry_type"
        ).fetchall()

        inflows: dict[str, float] = {}
        outflows: dict[str, float] = {}
        for r in rows:
            total = r["total"]
            if total >= 0:
                inflows[r["entry_type"]] = total
            else:
                outflows[r["entry_type"]] = abs(total)

        balance_row = conn.execute(
            "SELECT balance_after FROM treasury ORDER BY entry_id DESC LIMIT 1"
        ).fetchone()
        net_balance = balance_row["balance_after"] if balance_row else 0.0

        return {
            "inflows": inflows,
            "outflows": outflows,
            "net_balance": net_balance,
        }
    finally:
        conn.close()


@_routes.get("/treasury/ledger", response_model=list[dict[str, Any]])
async def get_treasury_ledger(
    entry_type: str | None = Query(None, description="Filter by entry type"),
    task_id: str | None = Query(None, description="Filter by task ID"),
    agent_did: str | None = Query(None, description="Filter by agent DID"),
):
    """Get treasury transaction ledger with optional filters."""
    conn = _connect()
    try:
        query = "SELECT * FROM treasury"
        conditions: list[str] = []
        params: list[str] = []

        if entry_type is not None:
            conditions.append("entry_type = ?")
            params.append(entry_type)
        if task_id is not None:
            conditions.append("task_id = ?")
            params.append(task_id)
        if agent_did is not None:
            conditions.append("agent_did = ?")
            params.append(agent_did)

        if conditions:
            query += " WHERE " + " AND ".join(conditions)
        query += " ORDER BY entry_id ASC"

        rows = conn.execute(query, params).fetchall()
        return [
            {
                "entry_id": r["entry_id"],
                "task_id": r["task_id"],
                "agent_did": r["agent_did"],
                "entry_type": r["entry_type"],
                "amount": r["amount"],
                "balance_after": r["balance_after"],
                "created_at": r["created_at"],
            }
            for r in rows
        ]
    finally:
        conn.close()


router.include_router(_routes)
v1_router.include_router(_routes)
