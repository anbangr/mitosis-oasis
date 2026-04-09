"""Execution API endpoints — task details, commitment, output submission, status.

Provides FastAPI routes for the execution branch:
- Task details and status queries
- Task commitment (stake lock)
- Output submission (LLM mode)
- Settlement results
- Session and agent task listings
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Union

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from oasis.config import PlatformConfig
from oasis.execution.commitment import commit_to_task
from oasis.execution.router import get_agent_tasks, get_session_tasks
from oasis.execution.runner import ExecutionDispatcher

# ---------------------------------------------------------------------------
# Module-level state
# ---------------------------------------------------------------------------

_db_path: str | None = None
_config: PlatformConfig = PlatformConfig()
_dispatcher: ExecutionDispatcher | None = None


def init_execution_db(db_path: str, config: PlatformConfig | None = None) -> None:
    """Set the execution database path and optional config."""
    global _db_path, _config, _dispatcher
    _db_path = db_path
    if config is not None:
        _config = config
    _dispatcher = ExecutionDispatcher(_config, _db_path)


def _get_db() -> str:
    if _db_path is None:
        raise HTTPException(503, "Execution database not initialised")
    return _db_path


def _get_dispatcher() -> ExecutionDispatcher:
    if _dispatcher is None:
        raise HTTPException(503, "Execution dispatcher not initialised")
    return _dispatcher


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(_get_db())
    conn.execute("PRAGMA foreign_keys = ON")
    conn.row_factory = sqlite3.Row
    return conn


# ---------------------------------------------------------------------------
# Pydantic request bodies
# ---------------------------------------------------------------------------

class CommitBody(BaseModel):
    agent_did: str = Field(..., min_length=1)


class OutputBody(BaseModel):
    agent_did: str = Field(..., min_length=1)
    output_data: str = Field(..., min_length=1)


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------

router = APIRouter(prefix="/api/execution", tags=["Execution"])


# ========================= Task details ======================================

@router.get("/tasks/{task_id}")
async def get_task(task_id: str):
    """Get task details including input data from the DAG node."""
    conn = _connect()
    try:
        task = conn.execute(
            "SELECT * FROM task_assignment WHERE task_id = ?",
            (task_id,),
        ).fetchone()
        if task is None:
            raise HTTPException(404, f"Task not found: {task_id}")

        # Look up DAG node for input schema
        node = conn.execute(
            "SELECT label, service_id, input_schema, output_schema, "
            "token_budget, timeout_ms FROM dag_node WHERE node_id = ?",
            (task["node_id"],),
        ).fetchone()

        node_info = None
        if node is not None:
            node_info = {
                "label": node["label"],
                "service_id": node["service_id"],
                "input_schema": (
                    json.loads(node["input_schema"])
                    if node["input_schema"]
                    else None
                ),
                "output_schema": (
                    json.loads(node["output_schema"])
                    if node["output_schema"]
                    else None
                ),
                "token_budget": node["token_budget"],
                "timeout_ms": node["timeout_ms"],
            }

        return {
            "task_id": task["task_id"],
            "session_id": task["session_id"],
            "node_id": task["node_id"],
            "agent_did": task["agent_did"],
            "status": task["status"],
            "created_at": task["created_at"],
            "node": node_info,
        }
    finally:
        conn.close()


# ========================= Commit to task ====================================

@router.post("/tasks/{task_id}/commit", status_code=200)
async def commit_task(task_id: str, body: CommitBody):
    """Commit to a task (lock stake)."""
    try:
        result = commit_to_task(task_id, body.agent_did, _get_db())
        return result
    except ValueError as exc:
        raise HTTPException(400, str(exc))


# ========================= Submit output =====================================

@router.post("/tasks/{task_id}/output", status_code=200)
async def submit_output(task_id: str, body: OutputBody):
    """Submit task output (LLM mode).

    The task must be in 'executing' state and the agent must be the assignee.
    """
    dispatcher = _get_dispatcher()
    try:
        result = dispatcher.receive_output(task_id, body.output_data, body.agent_did)
        return result
    except ValueError as exc:
        raise HTTPException(400, str(exc))


# ========================= Task status =======================================

@router.get("/tasks/{task_id}/status")
async def get_task_status(task_id: str):
    """Get task status including output and validation state."""
    dispatcher = _get_dispatcher()
    try:
        status = dispatcher.get_task_status(task_id)
        return {
            "task_id": status.task_id,
            "status": status.status,
            "agent_did": status.agent_did,
            "has_output": status.has_output,
            "has_validation": status.has_validation,
        }
    except ValueError as exc:
        raise HTTPException(404, str(exc))


# ========================= Settlement result =================================

@router.get("/tasks/{task_id}/settlement")
async def get_settlement(task_id: str):
    """Get settlement result for a completed task."""
    conn = _connect()
    try:
        task = conn.execute(
            "SELECT task_id FROM task_assignment WHERE task_id = ?",
            (task_id,),
        ).fetchone()
        if task is None:
            raise HTTPException(404, f"Task not found: {task_id}")

        settlement = conn.execute(
            "SELECT * FROM settlement WHERE task_id = ?",
            (task_id,),
        ).fetchone()
        if settlement is None:
            return {"task_id": task_id, "settled": False, "settlement": None}

        return {
            "task_id": task_id,
            "settled": True,
            "settlement": {
                "settlement_id": settlement["settlement_id"],
                "agent_did": settlement["agent_did"],
                "base_reward": settlement["base_reward"],
                "reputation_multiplier": settlement["reputation_multiplier"],
                "final_reward": settlement["final_reward"],
                "protocol_fee": settlement["protocol_fee"],
                "insurance_fee": settlement["insurance_fee"],
                "treasury_subsidy": settlement["treasury_subsidy"],
                "settled_at": settlement["settled_at"],
            },
        }
    finally:
        conn.close()


# ========================= Session tasks =====================================

@router.get("/sessions/{session_id}/tasks")
async def list_session_tasks(session_id: str):
    """List all tasks for a deployed session."""
    tasks = get_session_tasks(session_id, _get_db())
    return {"session_id": session_id, "tasks": tasks}


# ========================= Agent tasks =======================================

@router.get("/agents/{agent_did}/tasks")
async def list_agent_tasks(agent_did: str):
    """List all tasks assigned to an agent."""
    tasks = get_agent_tasks(agent_did, _get_db())
    return {"agent_did": agent_did, "tasks": tasks}
