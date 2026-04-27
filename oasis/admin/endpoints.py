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

import hmac
import json
import logging
import os
import sqlite3
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field, field_validator

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Module-level state
# ---------------------------------------------------------------------------

_gov_db_path: str | None = None

# Token is read once at import time so the env var must be set before the
# server starts.  Empty string means "no auth" — open access for dev/test.
_ADMIN_TOKEN: str = os.environ.get("ADMIN_TOKEN", "")

if not _ADMIN_TOKEN:
    logger.warning(
        "ADMIN_TOKEN is not set — all admin endpoints are publicly accessible. "
        "Set ADMIN_TOKEN before starting in production."
    )


async def _require_admin(x_admin_token: str | None = Header(None)) -> None:
    """FastAPI dependency: enforce X-Admin-Token header when ADMIN_TOKEN is set."""
    if not _ADMIN_TOKEN:
        return  # dev / test — no token configured
    if x_admin_token is None or not hmac.compare_digest(x_admin_token, _ADMIN_TOKEN):
        raise HTTPException(
            401 if x_admin_token is None else 403,
            "Invalid admin token",
        )


def set_admin_db(gov_db_path: str) -> None:
    """Register the governance DB path. Called during server startup.

    Also creates the shock_event_cache table so shock_id idempotency survives
    process restarts (e.g. GKE pod recycling on the Recreate deployment strategy).
    """
    global _gov_db_path
    _gov_db_path = gov_db_path
    conn = sqlite3.connect(gov_db_path)
    try:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS shock_event_cache (
                shock_id   TEXT PRIMARY KEY,
                result_json TEXT NOT NULL,
                created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.commit()
    finally:
        conn.close()


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
    strategy: str | None = Field(
        None,
        pattern=r"^(free_rider|coalition|honest|defector)$",
        description="Behavioural strategy label",
    )


class AgentBulkBody(BaseModel):
    agents: list[AgentSpec] = Field(..., min_length=1, max_length=1_000)


class RemoveHighRepBody(BaseModel):
    count: int = Field(..., ge=1, le=10_000, description="Number of highest-reputation agents to deactivate")


class MilestoneCrisisBody(BaseModel):
    milestone_id: str = Field(..., min_length=1, description="Milestone identifier to mark as quality crisis")

    @field_validator("milestone_id")
    @classmethod
    def strip_milestone_id(cls, v: str) -> str:
        return v.strip()


# ---------------------------------------------------------------------------
# Routers
# ---------------------------------------------------------------------------

_routes = APIRouter(tags=["Admin"], dependencies=[Depends(_require_admin)])

router = APIRouter(prefix="/api/admin", tags=["Admin"])
v1_router = APIRouter(prefix="/api/v1/admin", tags=["Admin"])

# In-process idempotency cache for /shock — keyed by shock_id.
# Bounded to _MAX_SHOCK_CACHE entries; oldest entry evicted when cap is reached.
_MAX_SHOCK_CACHE: int = 1_000
_shock_results: dict[str, dict[str, Any]] = {}

_SHOCK_FREE_RIDER_REP: float = 0.3
_SHOCK_COALITION_REP: float = 0.5


# ========================= Agent injection ===================================

@_routes.post("/agents/bulk", status_code=201, response_model=dict[str, Any])
async def bulk_register_agents(body: AgentBulkBody):
    """Inject multiple agents into the governance registry (shock event support).

    Uses INSERT OR REPLACE so callers can safely retry with the same DID.
    **Warning:** re-inserting an existing DID resets the agent row (including
    reputation_score back to the supplied value) while leaving any existing
    reputation_ledger rows intact — those entries will now reflect a history
    against a reset baseline.  Always supply a shock_id to /shock to prevent
    accidental re-application; use this endpoint directly only for deliberate
    re-injection.  Returns the count of agents written.
    """
    conn = _connect()
    try:
        for agent in body.agents:
            conn.execute(
                "INSERT OR REPLACE INTO agent_registry "
                "(agent_did, agent_type, capability_tier, display_name, reputation_score, strategy, active) "
                "VALUES (?, ?, ?, ?, ?, ?, 1)",
                (
                    agent.agent_did,
                    agent.agent_type,
                    agent.capability_tier,
                    agent.display_name,
                    agent.reputation_score,
                    agent.strategy,
                ),
            )
        conn.commit()
    finally:
        conn.close()
    return {"registered": len(body.agents), "agents": [a.agent_did for a in body.agents]}


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
        cursor = conn.execute(
            f"UPDATE agent_registry SET active = 0 WHERE agent_did IN ({placeholders})",
            dids,
        )
        conn.commit()
    finally:
        conn.close()
    return {"deactivated": cursor.rowcount, "agents": dids}


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
        "quality_crisis": affected > 0,
    }


# ========================= Shock event composite ============================

class ShockEventBody(BaseModel):
    free_rider_count: int = Field(10, ge=0, le=1_000)
    coalition_size: int = Field(5, ge=0, le=1_000)
    high_rep_remove_count: int = Field(20, ge=0, le=10_000)
    fail_milestone: str | None = Field(None)
    shock_id: str | None = Field(None, min_length=1, description="Idempotency key — same shock_id returns the cached result without re-applying")

    @field_validator("fail_milestone")
    @classmethod
    def strip_fail_milestone(cls, v: str | None) -> str | None:
        if v is None:
            return v
        stripped = v.strip()
        return stripped if stripped else None


@_routes.post("/shock", status_code=200, response_model=dict[str, Any])
async def apply_shock_event(body: ShockEventBody):
    """Apply a complete shock event in a single atomic transaction.

    Composite operation:
    1. Snapshot the N highest-reputation producers (before any injection)
    2. Inject free_rider_count T1 agents with free-rider strategy
    3. Inject coalition_size T3 agents with coalition strategy
    4. Deactivate the pre-snapshotted high-rep agents
    5. Mark fail_milestone sessions as quality crisis (if provided)

    All writes share one connection and commit atomically.

    **Always supply shock_id in production.**  Without it, each call re-applies
    all sub-operations.  Because steps 2–3 use INSERT OR REPLACE, a repeat call
    resets injected agents' reputation_score back to their initial value (0.3 /
    0.5) while leaving accumulated reputation_ledger history intact — silently
    corrupting ECP and PSR metrics.  With shock_id, the result is looked up first
    in the in-process dict (fast path) and then in the SQLite shock_event_cache
    table (durable across pod restarts), so the shock is applied exactly once.
    """
    if body.shock_id:
        # Fast path: in-process dict (sub-ms for repeated calls within the same pod).
        if body.shock_id in _shock_results:
            return _shock_results[body.shock_id]
        # Durable path: SQLite cache survives pod restarts.
        conn_check = _connect()
        try:
            row = conn_check.execute(
                "SELECT result_json FROM shock_event_cache WHERE shock_id = ?",
                (body.shock_id,),
            ).fetchone()
        finally:
            conn_check.close()
        if row:
            cached: dict[str, Any] = json.loads(row["result_json"])
            if len(_shock_results) >= _MAX_SHOCK_CACHE:
                del _shock_results[next(iter(_shock_results))]
            _shock_results[body.shock_id] = cached
            return cached

    summary: dict[str, Any] = {}
    conn = _connect()
    try:
        # Step 1 — snapshot high-rep candidates BEFORE injection so injected
        # agents (rep 0.3–0.5) cannot appear in the removal list.
        high_rep_candidates: list[str] = []
        if body.high_rep_remove_count > 0:
            rows = conn.execute(
                "SELECT agent_did FROM agent_registry "
                "WHERE agent_type = 'producer' AND active = 1 "
                "ORDER BY reputation_score DESC "
                "LIMIT ?",
                (body.high_rep_remove_count,),
            ).fetchall()
            high_rep_candidates = [r["agent_did"] for r in rows]

        # Step 2 — inject free-rider agents
        if body.free_rider_count > 0:
            for i in range(body.free_rider_count):
                conn.execute(
                    "INSERT OR REPLACE INTO agent_registry "
                    "(agent_did, agent_type, capability_tier, display_name, reputation_score, strategy, active) "
                    "VALUES (?, ?, ?, ?, ?, ?, 1)",
                    (f"did:shock:free-rider-{i + 1}", "producer", "t1",
                     f"Free-rider Agent {i + 1}", _SHOCK_FREE_RIDER_REP, "free_rider"),
                )
            summary["free_riders_injected"] = body.free_rider_count

        # Step 3 — inject coalition agents
        if body.coalition_size > 0:
            for i in range(body.coalition_size):
                conn.execute(
                    "INSERT OR REPLACE INTO agent_registry "
                    "(agent_did, agent_type, capability_tier, display_name, reputation_score, strategy, active) "
                    "VALUES (?, ?, ?, ?, ?, ?, 1)",
                    (f"did:shock:coalition-{i + 1}", "producer", "t3",
                     f"Coalition Agent {i + 1}", _SHOCK_COALITION_REP, "coalition"),
                )
            summary["coalition_injected"] = body.coalition_size

        # Step 4 — deactivate pre-snapshotted high-rep candidates
        if high_rep_candidates:
            placeholders = ",".join("?" * len(high_rep_candidates))
            conn.execute(
                f"UPDATE agent_registry SET active = 0 WHERE agent_did IN ({placeholders})",
                high_rep_candidates,
            )
            summary["high_rep_removed"] = len(high_rep_candidates)

        # Step 5 — mark milestone quality crisis
        if body.fail_milestone:
            result_row = conn.execute(
                "UPDATE legislative_session SET quality_crisis = 1 WHERE milestone_id = ?",
                (body.fail_milestone,),
            )
            affected = result_row.rowcount
            summary["milestone_crisis"] = {
                "milestone_id": body.fail_milestone,
                "sessions_affected": affected,
            }

        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    result: dict[str, Any] = {"shock_applied": True, "summary": summary}
    if body.shock_id:
        # Write to SQLite first (durable) then warm the in-process cache.
        conn_cache = _connect()
        try:
            conn_cache.execute(
                "INSERT OR IGNORE INTO shock_event_cache (shock_id, result_json) VALUES (?, ?)",
                (body.shock_id, json.dumps(result)),
            )
            conn_cache.commit()
        finally:
            conn_cache.close()
        if len(_shock_results) >= _MAX_SHOCK_CACHE:
            del _shock_results[next(iter(_shock_results))]
        _shock_results[body.shock_id] = result
    return result


router.include_router(_routes)
v1_router.include_router(_routes)
