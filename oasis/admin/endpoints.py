# =========== Copyright 2023 @ CAMEL-AI.org. All Rights Reserved. ===========
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
"""Admin API endpoints — shock event injection and experiment control.

Provides FastAPI routes for mid-run experiment manipulation:
- Bulk agent injection (free-riders, coalition blocs)
- High-reputation agent removal
- Milestone quality-crisis marking

These endpoints are called by the experiment orchestrator at shock_event.round
(default: round 100) during AgentCity experiment runs.
"""
from __future__ import annotations

import sqlite3
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Module-level state
# ---------------------------------------------------------------------------

_gov_db_path: str | None = None


def set_admin_db(gov_db_path: str) -> None:
    """Register the governance DB path. Called during server startup."""
    global _gov_db_path
    _gov_db_path = gov_db_path


def _get_gov_db() -> str:
    if _gov_db_path is None:
        raise HTTPException(503, "Admin database not initialised")
    return _gov_db_path


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(_get_gov_db())
    conn.execute("PRAGMA foreign_keys = ON")
    conn.row_factory = sqlite3.Row
    return conn


# ---------------------------------------------------------------------------
# Pydantic request models
# ---------------------------------------------------------------------------


class AgentSpec(BaseModel):
    agent_did: str = Field(..., min_length=1)
    agent_type: str = Field("producer", pattern=r"^(producer|clerk)$")
    capability_tier: str = Field("t1", pattern=r"^(t1|t3|t5)$")
    display_name: str = Field(..., min_length=1)
    reputation_score: float = Field(0.5, ge=0.0, le=1.0)
    strategy: str | None = Field(None, description="Behavioural strategy label (free_rider, coalition, etc.)")


class AgentBulkBody(BaseModel):
    agents: list[AgentSpec] = Field(..., min_length=1)


class RemoveHighRepBody(BaseModel):
    count: int = Field(..., ge=1, description="Number of highest-reputation agents to deactivate")


class MilestoneCrisisBody(BaseModel):
    milestone_id: str = Field(..., min_length=1, description="Milestone identifier to mark as quality crisis")


# ---------------------------------------------------------------------------
# Routers
# ---------------------------------------------------------------------------

_routes = APIRouter(tags=["Admin"])

router = APIRouter(prefix="/api/admin", tags=["Admin"])
v1_router = APIRouter(prefix="/api/v1/admin", tags=["Admin"])


# ========================= Agent injection ===================================

@_routes.post("/agents/bulk", status_code=201, response_model=dict[str, Any])
async def bulk_register_agents(body: AgentBulkBody):
    """Inject multiple agents into the governance registry (shock event support).

    Uses INSERT OR REPLACE so callers can safely retry. Returns the count of
    agents written.
    """
    conn = _connect()
    try:
        written = 0
        for agent in body.agents:
            conn.execute(
                "INSERT OR REPLACE INTO agent_registry "
                "(agent_did, agent_type, capability_tier, display_name, reputation_score, active) "
                "VALUES (?, ?, ?, ?, ?, 1)",
                (
                    agent.agent_did,
                    agent.agent_type,
                    agent.capability_tier,
                    agent.display_name,
                    agent.reputation_score,
                ),
            )
            written += 1
        conn.commit()
    finally:
        conn.close()
    return {"registered": written, "agents": [a.agent_did for a in body.agents]}


# ========================= High-rep removal ==================================

@_routes.post("/agents/remove-high-rep", status_code=200, response_model=dict[str, Any])
async def remove_high_rep_agents(body: RemoveHighRepBody):
    """Deactivate the N highest-reputation producer agents (shock event support).

    Sets active=0 rather than deleting rows to preserve history. Returns the
    list of deactivated agent DIDs.
    """
    conn = _connect()
    try:
        rows = conn.execute(
            "SELECT agent_did FROM agent_registry "
            "WHERE agent_type = 'producer' AND active = 1 "
            "ORDER BY reputation_score DESC "
            "LIMIT ?",
            (body.count,),
        ).fetchall()

        if not rows:
            return {"deactivated": 0, "agents": []}

        dids = [r["agent_did"] for r in rows]
        placeholders = ",".join("?" * len(dids))
        conn.execute(
            f"UPDATE agent_registry SET active = 0 WHERE agent_did IN ({placeholders})",
            dids,
        )
        conn.commit()
    finally:
        conn.close()
    return {"deactivated": len(dids), "agents": dids}


# ========================= Milestone quality crisis ==========================

@_routes.post("/sessions/milestone-crisis", status_code=200, response_model=dict[str, Any])
async def mark_milestone_crisis(body: MilestoneCrisisBody):
    """Mark all sessions belonging to a milestone as having a quality crisis.

    Sets quality_crisis=1 on all legislative_session rows with the given
    milestone_id. The orchestrator uses this to simulate milestone-05 failed
    quality audit in the AgentCity shock event.
    """
    conn = _connect()
    try:
        result = conn.execute(
            "UPDATE legislative_session SET quality_crisis = 1 "
            "WHERE milestone_id = ?",
            (body.milestone_id,),
        )
        affected = result.rowcount
        conn.commit()
    finally:
        conn.close()
    return {
        "milestone_id": body.milestone_id,
        "sessions_affected": affected,
        "quality_crisis": True,
    }


# ========================= Shock event composite ============================

class ShockEventBody(BaseModel):
    free_rider_count: int = Field(10, ge=0)
    coalition_size: int = Field(5, ge=0)
    high_rep_remove_count: int = Field(20, ge=0)
    fail_milestone: str | None = Field(None)


@_routes.post("/shock", status_code=200, response_model=dict[str, Any])
async def apply_shock_event(body: ShockEventBody):
    """Apply a complete shock event in a single request.

    Composite operation:
    1. Inject free_rider_count T1 agents with free-rider strategy
    2. Inject coalition_size T3 agents with coalition strategy
    3. Remove top high_rep_remove_count producer agents
    4. Mark fail_milestone as quality crisis (if provided)

    Returns a summary of all sub-operations.
    """
    summary: dict[str, Any] = {}

    # 1. Inject free-rider agents
    if body.free_rider_count > 0:
        free_riders = [
            AgentSpec(
                agent_did=f"did:shock:free-rider-{i + 1}",
                agent_type="producer",
                capability_tier="t1",
                display_name=f"Free-rider Agent {i + 1}",
                reputation_score=0.3,
                strategy="free_rider",
            )
            for i in range(body.free_rider_count)
        ]
        result = await bulk_register_agents(AgentBulkBody(agents=free_riders))
        summary["free_riders_injected"] = result["registered"]

    # 2. Inject coalition agents
    if body.coalition_size > 0:
        coalition = [
            AgentSpec(
                agent_did=f"did:shock:coalition-{i + 1}",
                agent_type="producer",
                capability_tier="t3",
                display_name=f"Coalition Agent {i + 1}",
                reputation_score=0.5,
                strategy="coalition",
            )
            for i in range(body.coalition_size)
        ]
        result = await bulk_register_agents(AgentBulkBody(agents=coalition))
        summary["coalition_injected"] = result["registered"]

    # 3. Remove high-reputation agents
    if body.high_rep_remove_count > 0:
        result = await remove_high_rep_agents(RemoveHighRepBody(count=body.high_rep_remove_count))
        summary["high_rep_removed"] = result["deactivated"]

    # 4. Mark milestone quality crisis
    if body.fail_milestone:
        result = await mark_milestone_crisis(MilestoneCrisisBody(milestone_id=body.fail_milestone))
        summary["milestone_crisis"] = {
            "milestone_id": body.fail_milestone,
            "sessions_affected": result["sessions_affected"],
        }

    return {"shock_applied": True, "summary": summary}


router.include_router(_routes)
v1_router.include_router(_routes)
