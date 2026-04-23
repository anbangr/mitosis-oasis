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

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from oasis.observatory.service import ObservatoryService

# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_service: ObservatoryService | None = None


def init_observatory_db(db_path: str) -> None:
    """Initialise the observatory service singleton."""
    global _service
    _service = ObservatoryService(db_path)


def _get_service() -> ObservatoryService:
    if _service is None:
        raise HTTPException(503, "Observatory database not initialised")
    return _service


# ---------------------------------------------------------------------------
# Shared route definitions
# ---------------------------------------------------------------------------

_routes = APIRouter(tags=["Observatory"])

# Public router aliases
router = APIRouter(prefix="/api/observatory", tags=["Observatory"])
v1_router = APIRouter(prefix="/api/v1/observatory", tags=["Observatory"])


# ========================= Summary ==========================================


@_routes.get("/summary", response_model=dict[str, Any])
async def get_summary():
    """Aggregate summary: sessions by state, agents by status, tasks, treasury, alerts."""
    return _get_service().get_summary()


# ========================= Leaderboard ======================================


@_routes.get("/agents/leaderboard", response_model=list[dict[str, Any]])
async def get_leaderboard(
    sort_by: str = Query("reputation_score", description="Sort metric"),
    limit: int = Query(20, ge=1, le=100),
    type: str | None = Query(None, description="Filter by agent type"),
):
    """Agent leaderboard ranked by configurable metric."""
    return _get_service().get_leaderboard(sort_by=sort_by, limit=limit, agent_type=type)


# ========================= Reputation timeseries =============================


@_routes.get("/reputation/timeseries", response_model=list[dict[str, Any]])
async def get_reputation_timeseries(
    agent_did: str | None = Query(None),
    since: str | None = Query(None, description="ISO timestamp lower bound"),
    until: str | None = Query(None, description="ISO timestamp upper bound"),
):
    """Reputation ledger time-series data."""
    return _get_service().get_reputation_timeseries(
        agent_did=agent_did, since=since, until=until
    )


# ========================= Treasury timeseries ===============================


@_routes.get("/treasury/timeseries", response_model=list[dict[str, Any]])
async def get_treasury_timeseries():
    """Running balance over time from the treasury table."""
    return _get_service().get_treasury_timeseries()


# ========================= Events (paginated) ================================


@_routes.get("/events", response_model=list[dict[str, Any]])
async def get_events(
    event_type: str | None = Query(None, description="Filter by event type"),
    session_id: str | None = Query(None),
    agent_did: str | None = Query(None),
    since: int = Query(0, description="Sequence number lower bound"),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
):
    """Paginated event_log query."""
    return _get_service().get_events(
        event_type=event_type,
        session_id=session_id,
        agent_did=agent_did,
        since=since,
        limit=limit,
        offset=offset,
    )


# ========================= Session timeline ==================================


@_routes.get("/sessions/timeline", response_model=list[dict[str, Any]])
async def get_sessions_timeline():
    """Session state history for Gantt rendering."""
    return _get_service().get_sessions_timeline()


# ========================= Execution heatmap =================================


@_routes.get("/execution/heatmap", response_model=dict[str, Any])
async def get_execution_heatmap():
    """Pivot task_assignment by agent x task — status matrix for heatmap rendering."""
    return _get_service().get_execution_heatmap()


router.include_router(_routes)
v1_router.include_router(_routes)
