# Copyright 2023 The CAMEL-AI.org. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
# =========== Copyright 2023 @ CAMEL-AI.org. All Rights Reserved. ===========
"""Execution API endpoints — task details, commitment, output submission, status.

Provides FastAPI routes for the execution branch:
- Task details and status queries
- Task commitment (stake lock)
- Output submission (LLM mode)
- Settlement results
- Session and agent task listings
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from oasis.config import PlatformConfig
from oasis.execution.service import ExecutionService, ExecutionServiceError

# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_service: ExecutionService | None = None


def init_execution_db(db_path: str, config: PlatformConfig | None = None) -> None:
    """Initialise the execution service singleton."""
    global _service
    _service = ExecutionService(db_path, config)


def _get_service() -> ExecutionService:
    if _service is None:
        raise HTTPException(503, "Execution database not initialised")
    return _service


# ---------------------------------------------------------------------------
# Pydantic request bodies
# ---------------------------------------------------------------------------


class CommitBody(BaseModel):
    agent_did: str = Field(..., min_length=1)


class OutputBody(BaseModel):
    agent_did: str = Field(..., min_length=1)
    output_data: str = Field(..., min_length=1)


# ---------------------------------------------------------------------------
# Shared route definitions
# ---------------------------------------------------------------------------

_routes = APIRouter(tags=["Execution"])

# Public router aliases
router = APIRouter(prefix="/api/execution", tags=["Execution"])
v1_router = APIRouter(prefix="/api/v1/execution", tags=["Execution"])


# ========================= Task details ======================================


@_routes.get("/tasks/{task_id}", response_model=dict[str, Any])
async def get_task(task_id: str):
    """Get task details including input data from the DAG node."""
    svc = _get_service()
    try:
        return svc.get_task(task_id)
    except ExecutionServiceError as exc:
        raise HTTPException(exc.status_code, str(exc))


# ========================= Commit to task ====================================


@_routes.post("/tasks/{task_id}/commit", status_code=200, response_model=dict[str, Any])
async def commit_task(task_id: str, body: CommitBody):
    """Commit to a task (lock stake)."""
    svc = _get_service()
    try:
        return svc.commit_task(task_id, body.agent_did)
    except ExecutionServiceError as exc:
        raise HTTPException(exc.status_code, str(exc))


# ========================= Submit output =====================================


@_routes.post("/tasks/{task_id}/output", status_code=200, response_model=dict[str, Any])
async def submit_output(task_id: str, body: OutputBody):
    """Submit task output (LLM mode).

    The task must be in 'executing' state and the agent must be the assignee.
    """
    svc = _get_service()
    try:
        return svc.submit_output(task_id, body.output_data, body.agent_did)
    except ExecutionServiceError as exc:
        raise HTTPException(exc.status_code, str(exc))


# ========================= Task status =======================================


@_routes.get("/tasks/{task_id}/status", response_model=dict[str, Any])
async def get_task_status(task_id: str):
    """Get task status including output and validation state."""
    svc = _get_service()
    try:
        return svc.get_task_status(task_id)
    except ExecutionServiceError as exc:
        raise HTTPException(exc.status_code, str(exc))


# ========================= Settlement result =================================


@_routes.get("/tasks/{task_id}/settlement", response_model=dict[str, Any])
async def get_settlement(task_id: str):
    """Get settlement result for a completed task."""
    svc = _get_service()
    try:
        return svc.get_settlement(task_id)
    except ExecutionServiceError as exc:
        raise HTTPException(exc.status_code, str(exc))


# ========================= Session tasks =====================================


@_routes.get("/sessions/{session_id}/tasks", response_model=dict[str, Any])
async def list_session_tasks(session_id: str):
    """List all tasks for a deployed session."""
    return _get_service().list_session_tasks(session_id)


# ========================= Agent tasks =======================================


@_routes.get("/agents/{agent_did}/tasks", response_model=dict[str, Any])
async def list_agent_tasks(agent_did: str):
    """List all tasks assigned to an agent."""
    return _get_service().list_agent_tasks(agent_did)


router.include_router(_routes)
v1_router.include_router(_routes)
