"""Mitosis-OASIS FastAPI HTTP server.

Wraps the existing Platform + Channel with REST endpoints so that external
agents (ZeroClaw) can interact with the simulation via HTTP instead of being
embedded CAMEL agents.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import sqlite3
import tempfile
import time
import uuid
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any

from fastapi import FastAPI, HTTPException, Query
from fastapi import WebSocket
from pydantic import BaseModel

from oasis.governance import endpoints as gov_ep
from oasis.execution import endpoints as exec_ep
from oasis.adjudication import endpoints as adj_ep
from oasis.observatory import endpoints as obs_ep
from oasis.governance.endpoints import init_governance_db, router as governance_router, v1_router as governance_v1_router
from oasis.execution.endpoints import init_execution_db, router as execution_router, v1_router as execution_v1_router
from oasis.execution.schema import create_execution_tables
from oasis.adjudication.endpoints import init_adjudication_db, router as adjudication_router, v1_router as adjudication_v1_router
from oasis.adjudication.schema import create_adjudication_tables
from oasis.observatory.endpoints import init_observatory_db, router as observatory_router, v1_router as observatory_v1_router
from oasis.observatory.dashboard import router as dashboard_router
from oasis.observatory.event_bus import EventBus
from oasis.observatory.websocket import websocket_events
from oasis.social_platform.channel import Channel
from oasis.social_platform.platform import Platform
from oasis.social_platform.typing import ActionType

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Global state (populated during startup)
# ---------------------------------------------------------------------------

channel: Channel | None = None
platform: Platform | None = None
_platform_task: asyncio.Task | None = None


# ---------------------------------------------------------------------------
# Lifespan: spin up Platform on startup, shut it down gracefully
# ---------------------------------------------------------------------------


@asynccontextmanager
async def lifespan(app: FastAPI):
    global channel, platform, _platform_task

    channel = Channel()
    # Platform needs at least a db_path and a channel.
    # Use an in-memory SQLite database so the server can start without config.
    platform = Platform(
        db_path=":memory:",
        channel=channel,
    )
    _platform_task = asyncio.create_task(platform.running())

    # Initialise governance database (in-memory, colocated with platform DB)
    _gov_db = os.path.join(tempfile.gettempdir(), f"oasis_gov_{os.getpid()}.db")
    init_governance_db(_gov_db)

    _exec_db = os.path.join(tempfile.gettempdir(), f"oasis_exec_{os.getpid()}.db")
    create_execution_tables(_exec_db)
    init_execution_db(_exec_db)

    _adj_db = os.path.join(tempfile.gettempdir(), f"oasis_adj_{os.getpid()}.db")
    create_adjudication_tables(_adj_db)
    init_adjudication_db(_adj_db)

    _obs_db = os.path.join(tempfile.gettempdir(), f"oasis_obs_{os.getpid()}.db")
    init_observatory_db(_obs_db)

    # Also initialize the EventBus singleton with the observatory DB
    EventBus.get_instance(_obs_db)

    logger.info("Mitosis-OASIS platform started")

    yield  # Server is now running

    # Graceful shutdown: send EXIT action
    if channel is not None:
        try:
            await channel.write_to_receive_queue((0, None, ActionType.EXIT.value))
            if _platform_task is not None:
                await asyncio.wait_for(_platform_task, timeout=5.0)
        except (asyncio.TimeoutError, Exception) as exc:
            logger.warning("Platform shutdown issue: %s", exc)
            if _platform_task is not None:
                _platform_task.cancel()
    logger.info("Mitosis-OASIS platform stopped")


# ---------------------------------------------------------------------------
# FastAPI application
# ---------------------------------------------------------------------------

app = FastAPI(
    title="Mitosis-OASIS API",
    description="REST API for OASIS social simulation platform",
    version="0.4.0",
    lifespan=lifespan,
)

# Include governance API router (P8)
app.include_router(governance_router)
app.include_router(governance_v1_router)

# Include execution API router (P13)
app.include_router(execution_router)
app.include_router(execution_v1_router)

# Include adjudication API router (P15)
app.include_router(adjudication_router)
app.include_router(adjudication_v1_router)

# Include observatory API router + dashboard (P17)
app.include_router(observatory_router)
app.include_router(observatory_v1_router)
app.include_router(dashboard_router)


# ---------------------------------------------------------------------------
# Observatory WebSocket endpoint
# ---------------------------------------------------------------------------


@app.websocket("/ws/events")
async def ws_events(ws: WebSocket):
    """WebSocket endpoint for real-time event streaming."""
    bus = EventBus.get_instance()
    await websocket_events(ws, bus)


# ---------------------------------------------------------------------------
# Internal dispatch helper
# ---------------------------------------------------------------------------


async def _dispatch(action_type: ActionType, agent_id: int,
                    message: Any = None) -> Any:
    """Send an action through the channel and await the platform response."""
    if channel is None:
        raise HTTPException(status_code=503, detail="Platform not running")
    msg_id = await channel.write_to_receive_queue(
        (agent_id, message, action_type.value))
    _, _, result = await channel.read_from_send_queue(msg_id)
    return result


# ---------------------------------------------------------------------------
# Pydantic request models
# ---------------------------------------------------------------------------


class SignUpBody(BaseModel):
    agent_id: int
    user_name: str
    name: str
    bio: str = ""


class CreatePostBody(BaseModel):
    agent_id: int
    content: str


class AgentIdBody(BaseModel):
    agent_id: int


class AgentIdWithContentBody(BaseModel):
    agent_id: int
    content: str


class FollowBody(BaseModel):
    agent_id: int
    target_user_id: int


class CreateCommentBody(BaseModel):
    agent_id: int
    content: str


class QuotePostBody(BaseModel):
    agent_id: int
    content: str


class ReportPostBody(BaseModel):
    agent_id: int
    reason: str = ""


class SendToGroupBody(BaseModel):
    agent_id: int
    content: str


class CreateGroupBody(BaseModel):
    agent_id: int
    group_name: str


class PurchaseProductBody(BaseModel):
    agent_id: int
    quantity: int = 1


class ObservationBatchBody(BaseModel):
    agent_ids: list[str]
    limit: int = 20
    agent_dids: dict[str, str] | None = None


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------


@app.get("/api/health", tags=["Meta"])
async def health():
    """Health check endpoint."""
    return {"status": "ok", "platform_running": platform is not None}


# ---------------------------------------------------------------------------
# Seed demo data
# ---------------------------------------------------------------------------


@app.post("/api/seed-demo", tags=["Meta"])
async def seed_demo():
    """Populate realistic demo data across all branches.

    Idempotent — skips seeding if data already exists.
    """
    gov_db = gov_ep._db_path
    exec_db = exec_ep._service._db_path if exec_ep._service is not None else None
    adj_db = adj_ep._db_path
    obs_db = obs_ep._service._db_path if obs_ep._service is not None else None

    if not all([gov_db, exec_db, adj_db, obs_db]):
        raise HTTPException(503, "Not all databases are initialised")

    summary: dict[str, Any] = {}

    # --- Governance seed ------------------------------------------------
    conn = sqlite3.connect(gov_db)
    conn.execute("PRAGMA foreign_keys = ON")
    row = conn.execute("SELECT COUNT(*) as c FROM agent_registry WHERE agent_type != 'clerk'").fetchone()
    if row[0] > 0:
        summary["governance"] = "already seeded"
    else:
        agents = [
            ("did:demo:legislator-1", "producer", "Alice Legislator",  "alice@demo.dev",  0.85),
            ("did:demo:legislator-2", "producer", "Bob Legislator",    "bob@demo.dev",    0.72),
            ("did:demo:executor-1",   "producer", "Carol Executor",    "carol@demo.dev",  0.90),
            ("did:demo:executor-2",   "producer", "Dave Executor",     "dave@demo.dev",   0.65),
            ("did:demo:adjudicator-1","producer", "Eve Adjudicator",   "eve@demo.dev",    0.78),
            ("did:demo:adjudicator-2","producer", "Frank Adjudicator", "frank@demo.dev",  0.60),
            ("did:demo:observer-1",   "producer", "Grace Observer",    "grace@demo.dev",  0.88),
            ("did:demo:observer-2",   "producer", "Hank Observer",     "hank@demo.dev",   0.55),
        ]
        conn.executemany(
            "INSERT OR IGNORE INTO agent_registry "
            "(agent_did, agent_type, display_name, human_principal, reputation_score) "
            "VALUES (?, ?, ?, ?, ?)",
            agents,
        )

        sessions = [
            ("sess-demo-draft",   "SESSION_INIT", 5000.0),
            ("sess-demo-voting",  "BIDDING_OPEN", 8000.0),
            ("sess-demo-enacted", "DEPLOYED",     12000.0),
        ]
        for sid, state, budget in sessions:
            conn.execute(
                "INSERT OR IGNORE INTO legislative_session "
                "(session_id, state, mission_budget_cap) VALUES (?, ?, ?)",
                (sid, state, budget),
            )

        rep_entries = [
            ("did:demo:legislator-1", 0.50, 0.70, 0.80, "Initial assessment"),
            ("did:demo:legislator-1", 0.70, 0.85, 0.90, "Task completion bonus"),
            ("did:demo:executor-1",   0.50, 0.75, 0.85, "Initial assessment"),
            ("did:demo:executor-1",   0.75, 0.90, 0.95, "Excellent output quality"),
            ("did:demo:adjudicator-1",0.50, 0.65, 0.70, "Initial assessment"),
            ("did:demo:adjudicator-1",0.65, 0.78, 0.80, "Fair adjudication record"),
            ("did:demo:observer-1",   0.50, 0.80, 0.88, "Initial assessment"),
            ("did:demo:observer-2",   0.50, 0.55, 0.50, "Initial assessment"),
        ]
        conn.executemany(
            "INSERT INTO reputation_ledger "
            "(agent_did, old_score, new_score, performance_score, reason) "
            "VALUES (?, ?, ?, ?, ?)",
            rep_entries,
        )
        conn.commit()
        summary["governance"] = {"agents": len(agents), "sessions": len(sessions), "reputation_entries": len(rep_entries)}
    conn.close()

    # --- Execution seed -------------------------------------------------
    conn = sqlite3.connect(exec_db)
    conn.execute("PRAGMA foreign_keys = OFF")
    row = conn.execute("SELECT COUNT(*) as c FROM task_assignment").fetchone()
    if row[0] > 0:
        summary["execution"] = "already seeded"
    else:
        tasks = [
            (str(uuid.uuid4()), "sess-demo-enacted", "n1", "did:demo:executor-1", "assigned"),
            (str(uuid.uuid4()), "sess-demo-enacted", "n2", "did:demo:executor-1", "running"),
            (str(uuid.uuid4()), "sess-demo-enacted", "n3", "did:demo:executor-2", "completed"),
            (str(uuid.uuid4()), "sess-demo-enacted", "n4", "did:demo:executor-2", "settled"),
            (str(uuid.uuid4()), "sess-demo-voting",  "n5", "did:demo:executor-1", "failed"),
        ]
        conn.executemany(
            "INSERT OR IGNORE INTO task_assignment "
            "(task_id, session_id, node_id, agent_did, status) VALUES (?, ?, ?, ?, ?)",
            tasks,
        )
        conn.commit()
        summary["execution"] = {"task_assignments": len(tasks)}
    conn.close()

    # --- Adjudication seed ----------------------------------------------
    conn = sqlite3.connect(adj_db)
    conn.execute("PRAGMA foreign_keys = OFF")
    row = conn.execute("SELECT COUNT(*) as c FROM treasury").fetchone()
    if row[0] > 0:
        summary["adjudication"] = "already seeded"
    else:
        # Create stub tables needed for FK references and guardian alerts
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS task_assignment (
                task_id TEXT PRIMARY KEY,
                session_id TEXT, node_id TEXT, agent_did TEXT, status TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS agent_registry (
                agent_did TEXT PRIMARY KEY,
                agent_type TEXT, 
                capability_tier TEXT CHECK(capability_tier IN ('t1', 't3', 't5')),
                display_name TEXT, human_principal TEXT,
                reputation_score REAL DEFAULT 0.5,
                registered_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, active BOOLEAN DEFAULT 1
            );
            CREATE TABLE IF NOT EXISTS guardian_alert (
                alert_id TEXT PRIMARY KEY, task_id TEXT NOT NULL,
                alert_type TEXT NOT NULL, severity TEXT NOT NULL,
                details TEXT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)
        # Insert stub tasks for FK references
        conn.execute(
            "INSERT OR IGNORE INTO task_assignment (task_id, session_id, node_id, agent_did, status) "
            "VALUES ('task-alert-1', 'sess-demo-enacted', 'n1', 'did:demo:executor-1', 'running')"
        )
        conn.execute(
            "INSERT OR IGNORE INTO task_assignment (task_id, session_id, node_id, agent_did, status) "
            "VALUES ('task-alert-2', 'sess-demo-enacted', 'n2', 'did:demo:executor-2', 'failed')"
        )
        # Insert stub agents for FK
        conn.execute(
            "INSERT OR IGNORE INTO agent_registry (agent_did, agent_type, display_name) "
            "VALUES ('did:demo:executor-1', 'producer', 'Carol Executor')"
        )
        conn.execute(
            "INSERT OR IGNORE INTO agent_registry (agent_did, agent_type, display_name) "
            "VALUES ('did:demo:executor-2', 'producer', 'Dave Executor')"
        )

        alerts = [
            ("alert-demo-1", "task-alert-1", "timeout", "high", "Task exceeded timeout by 200%"),
            ("alert-demo-2", "task-alert-2", "schema_violation", "critical", "Output schema mismatch"),
        ]
        conn.executemany(
            "INSERT OR IGNORE INTO guardian_alert "
            "(alert_id, task_id, alert_type, severity, details) VALUES (?, ?, ?, ?, ?)",
            alerts,
        )

        decisions = [
            (str(uuid.uuid4()), "alert-demo-1", None, "did:demo:executor-1", "warning",  "medium", "First offence — warning issued"),
            (str(uuid.uuid4()), "alert-demo-2", None, "did:demo:executor-2", "slash",    "high",   "Repeated schema violations"),
            (str(uuid.uuid4()), None,           None, "did:demo:executor-2", "freeze",   "critical","Frozen pending investigation"),
        ]
        conn.executemany(
            "INSERT OR IGNORE INTO adjudication_decision "
            "(decision_id, alert_id, flag_id, agent_did, decision_type, severity, reason) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            decisions,
        )

        treasury_entries = [
            (None, None,                  "seed",   10000.0, 10000.0),
            ("task-alert-1", "did:demo:executor-1", "reward",  500.0, 10500.0),
            ("task-alert-2", "did:demo:executor-2", "slash",  -200.0, 10300.0),
            (None, None,                  "fee",    -50.0,   10250.0),
            (None, "did:demo:executor-1", "reward",  300.0, 10550.0),
        ]
        conn.executemany(
            "INSERT INTO treasury "
            "(task_id, agent_did, entry_type, amount, balance_after) VALUES (?, ?, ?, ?, ?)",
            treasury_entries,
        )
        conn.commit()
        summary["adjudication"] = {
            "guardian_alerts": len(alerts),
            "adjudication_decisions": len(decisions),
            "treasury_entries": len(treasury_entries),
        }
    conn.close()

    # --- Observatory seed (event_log + cross-branch tables for summary) --
    conn = sqlite3.connect(obs_db)
    conn.execute("PRAGMA foreign_keys = OFF")
    row = conn.execute("SELECT COUNT(*) as c FROM event_log").fetchone()
    if row[0] > 0:
        summary["observatory"] = "already seeded"
    else:
        # Create governance/execution/adjudication tables in observatory DB
        # so that summary/leaderboard/heatmap queries work
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS agent_registry (
                agent_did TEXT PRIMARY KEY, agent_type TEXT NOT NULL,
                capability_tier TEXT CHECK(capability_tier IN ('t1', 't3', 't5')),
                display_name TEXT NOT NULL, human_principal TEXT,
                reputation_score REAL NOT NULL DEFAULT 0.5,
                registered_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                active BOOLEAN DEFAULT 1
            );
            CREATE TABLE IF NOT EXISTS agent_balance (
                agent_did TEXT PRIMARY KEY, total_balance REAL DEFAULT 100.0,
                locked_stake REAL DEFAULT 0.0, available_balance REAL DEFAULT 100.0
            );
            CREATE TABLE IF NOT EXISTS legislative_session (
                session_id TEXT PRIMARY KEY, state TEXT NOT NULL DEFAULT 'SESSION_INIT',
                epoch INTEGER DEFAULT 0, parent_session_id TEXT, parent_node_id TEXT,
                mission_budget_cap REAL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, failed_reason TEXT
            );
            CREATE TABLE IF NOT EXISTS task_assignment (
                task_id TEXT PRIMARY KEY, session_id TEXT NOT NULL,
                node_id TEXT NOT NULL, agent_did TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS guardian_alert (
                alert_id TEXT PRIMARY KEY, task_id TEXT NOT NULL,
                alert_type TEXT NOT NULL, severity TEXT NOT NULL,
                details TEXT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS treasury (
                entry_id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id TEXT, agent_did TEXT, entry_type TEXT NOT NULL,
                amount REAL NOT NULL, balance_after REAL NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS reputation_ledger (
                entry_id INTEGER PRIMARY KEY AUTOINCREMENT,
                agent_did TEXT NOT NULL, old_score REAL NOT NULL,
                new_score REAL NOT NULL, performance_score REAL,
                lambda REAL, reason TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)

        # Agents
        obs_agents = [
            ("did:demo:legislator-1", "producer", "Alice Legislator",  "alice@demo.dev",  0.85),
            ("did:demo:legislator-2", "producer", "Bob Legislator",    "bob@demo.dev",    0.72),
            ("did:demo:executor-1",   "producer", "Carol Executor",    "carol@demo.dev",  0.90),
            ("did:demo:executor-2",   "producer", "Dave Executor",     "dave@demo.dev",   0.65),
            ("did:demo:adjudicator-1","producer", "Eve Adjudicator",   "eve@demo.dev",    0.78),
            ("did:demo:adjudicator-2","producer", "Frank Adjudicator", "frank@demo.dev",  0.60),
            ("did:demo:observer-1",   "producer", "Grace Observer",    "grace@demo.dev",  0.88),
            ("did:demo:observer-2",   "producer", "Hank Observer",     "hank@demo.dev",   0.55),
        ]
        conn.executemany(
            "INSERT OR IGNORE INTO agent_registry "
            "(agent_did, agent_type, display_name, human_principal, reputation_score) "
            "VALUES (?, ?, ?, ?, ?)",
            obs_agents,
        )
        # Agent balances
        balances = [
            ("did:demo:legislator-1", 150.0, 10.0, 140.0),
            ("did:demo:legislator-2", 100.0,  0.0, 100.0),
            ("did:demo:executor-1",   200.0, 25.0, 175.0),
            ("did:demo:executor-2",    80.0,  5.0,  75.0),
            ("did:demo:adjudicator-1",120.0,  0.0, 120.0),
            ("did:demo:adjudicator-2", 95.0,  0.0,  95.0),
            ("did:demo:observer-1",   110.0,  0.0, 110.0),
            ("did:demo:observer-2",    90.0,  0.0,  90.0),
        ]
        conn.executemany(
            "INSERT OR IGNORE INTO agent_balance "
            "(agent_did, total_balance, locked_stake, available_balance) "
            "VALUES (?, ?, ?, ?)",
            balances,
        )
        # Sessions
        conn.execute("INSERT OR IGNORE INTO legislative_session (session_id, state, mission_budget_cap) VALUES (?, ?, ?)",
                     ("sess-demo-draft", "SESSION_INIT", 5000.0))
        conn.execute("INSERT OR IGNORE INTO legislative_session (session_id, state, mission_budget_cap) VALUES (?, ?, ?)",
                     ("sess-demo-voting", "BIDDING_OPEN", 8000.0))
        conn.execute("INSERT OR IGNORE INTO legislative_session (session_id, state, mission_budget_cap) VALUES (?, ?, ?)",
                     ("sess-demo-enacted", "DEPLOYED", 12000.0))
        # Task assignments
        obs_tasks = [
            ("task-obs-1", "sess-demo-enacted", "n1", "did:demo:executor-1", "assigned"),
            ("task-obs-2", "sess-demo-enacted", "n2", "did:demo:executor-1", "running"),
            ("task-obs-3", "sess-demo-enacted", "n3", "did:demo:executor-2", "completed"),
            ("task-obs-4", "sess-demo-enacted", "n4", "did:demo:executor-2", "settled"),
            ("task-obs-5", "sess-demo-voting",  "n5", "did:demo:executor-1", "failed"),
        ]
        conn.executemany(
            "INSERT OR IGNORE INTO task_assignment "
            "(task_id, session_id, node_id, agent_did, status) VALUES (?, ?, ?, ?, ?)",
            obs_tasks,
        )
        # Guardian alerts
        conn.execute(
            "INSERT OR IGNORE INTO guardian_alert (alert_id, task_id, alert_type, severity, details) "
            "VALUES (?, ?, ?, ?, ?)",
            ("alert-obs-1", "task-obs-2", "timeout", "high", "Task exceeded timeout"),
        )
        conn.execute(
            "INSERT OR IGNORE INTO guardian_alert (alert_id, task_id, alert_type, severity, details) "
            "VALUES (?, ?, ?, ?, ?)",
            ("alert-obs-2", "task-obs-5", "schema_violation", "critical", "Output mismatch"),
        )
        # Treasury
        obs_treasury = [
            (None, None, "seed", 10000.0, 10000.0),
            ("task-obs-3", "did:demo:executor-2", "reward", 500.0, 10500.0),
            ("task-obs-5", "did:demo:executor-1", "slash", -200.0, 10300.0),
            (None, None, "fee", -50.0, 10250.0),
        ]
        conn.executemany(
            "INSERT INTO treasury (task_id, agent_did, entry_type, amount, balance_after) "
            "VALUES (?, ?, ?, ?, ?)",
            obs_treasury,
        )
        # Reputation ledger
        obs_rep = [
            ("did:demo:legislator-1", 0.50, 0.85, 0.90, "Consistent legislation quality"),
            ("did:demo:executor-1",   0.50, 0.90, 0.95, "Excellent task execution"),
            ("did:demo:adjudicator-1",0.50, 0.78, 0.80, "Fair adjudication"),
            ("did:demo:observer-1",   0.50, 0.88, 0.88, "Active monitoring"),
        ]
        conn.executemany(
            "INSERT INTO reputation_ledger "
            "(agent_did, old_score, new_score, performance_score, reason) "
            "VALUES (?, ?, ?, ?, ?)",
            obs_rep,
        )

        # Event log — spread over 24 hours
        now = time.time()
        hour = 3600.0
        events = [
            (str(uuid.uuid4()), "SESSION_CREATED",         now - 23*hour, "sess-demo-draft",   "did:demo:legislator-1", json.dumps({"budget": 5000}),  1),
            (str(uuid.uuid4()), "SESSION_CREATED",         now - 22*hour, "sess-demo-voting",  "did:demo:legislator-2", json.dumps({"budget": 8000}),  2),
            (str(uuid.uuid4()), "SESSION_CREATED",         now - 21*hour, "sess-demo-enacted", "did:demo:legislator-1", json.dumps({"budget": 12000}), 3),
            (str(uuid.uuid4()), "SESSION_STATE_CHANGED",   now - 20*hour, "sess-demo-voting",  None,                    json.dumps({"from": "SESSION_INIT", "to": "BIDDING_OPEN"}), 4),
            (str(uuid.uuid4()), "SESSION_STATE_CHANGED",   now - 19*hour, "sess-demo-enacted", None,                    json.dumps({"from": "SESSION_INIT", "to": "DEPLOYED"}), 5),
            (str(uuid.uuid4()), "IDENTITY_VERIFIED",       now - 18*hour, "sess-demo-enacted", "did:demo:executor-1",   json.dumps({"method": "DID"}), 6),
            (str(uuid.uuid4()), "PROPOSAL_SUBMITTED",      now - 17*hour, "sess-demo-enacted", "did:demo:legislator-1", json.dumps({"nodes": 4}), 7),
            (str(uuid.uuid4()), "VOTE_CAST",               now - 16*hour, "sess-demo-voting",  "did:demo:legislator-1", json.dumps({"preference": [1, 2]}), 8),
            (str(uuid.uuid4()), "VOTE_CAST",               now - 15.5*hour,"sess-demo-voting", "did:demo:legislator-2", json.dumps({"preference": [2, 1]}), 9),
            (str(uuid.uuid4()), "BID_SUBMITTED",           now - 15*hour, "sess-demo-voting",  "did:demo:executor-1",   json.dumps({"stake": 0.5}), 10),
            (str(uuid.uuid4()), "TASK_ASSIGNED",           now - 14*hour, "sess-demo-enacted", "did:demo:executor-1",   json.dumps({"node_id": "n1"}), 11),
            (str(uuid.uuid4()), "TASK_ASSIGNED",           now - 13.5*hour,"sess-demo-enacted","did:demo:executor-2",   json.dumps({"node_id": "n3"}), 12),
            (str(uuid.uuid4()), "TASK_COMMITTED",          now - 13*hour, "sess-demo-enacted", "did:demo:executor-1",   json.dumps({"stake": 25.0}), 13),
            (str(uuid.uuid4()), "TASK_EXECUTED",           now - 12*hour, "sess-demo-enacted", "did:demo:executor-2",   json.dumps({"latency_ms": 4500}), 14),
            (str(uuid.uuid4()), "TASK_VALIDATED",          now - 11*hour, "sess-demo-enacted", "did:demo:executor-2",   json.dumps({"quality": 0.92}), 15),
            (str(uuid.uuid4()), "TASK_SETTLED",            now - 10*hour, "sess-demo-enacted", "did:demo:executor-2",   json.dumps({"reward": 500.0}), 16),
            (str(uuid.uuid4()), "GUARDIAN_ALERT_RAISED",   now - 9*hour,  "sess-demo-enacted", "did:demo:executor-1",   json.dumps({"alert_type": "timeout"}), 17),
            (str(uuid.uuid4()), "STAKE_SLASHED",           now - 8*hour,  "sess-demo-enacted", "did:demo:executor-1",   json.dumps({"amount": 200.0}), 18),
            (str(uuid.uuid4()), "REPUTATION_UPDATED",      now - 7*hour,  "sess-demo-enacted", "did:demo:executor-1",   json.dumps({"old": 0.90, "new": 0.85}), 19),
            (str(uuid.uuid4()), "COORDINATION_FLAGGED",    now - 6*hour,  "sess-demo-voting",  "did:demo:legislator-1", json.dumps({"pair": "legislator-1/legislator-2", "score": 0.78}), 20),
            (str(uuid.uuid4()), "TREASURY_ENTRY",          now - 5*hour,  None,                None,                    json.dumps({"type": "fee", "amount": -50.0}), 21),
            (str(uuid.uuid4()), "DELIBERATION_ROUND",      now - 4*hour,  "sess-demo-voting",  "did:demo:legislator-1", json.dumps({"round": 1, "message": "Propose budget increase"}), 22),
            (str(uuid.uuid4()), "REGULATORY_DECISION_MADE",now - 3*hour,  "sess-demo-enacted", "did:demo:adjudicator-1",json.dumps({"approved": True}), 23),
            (str(uuid.uuid4()), "SPEC_COMPILED",           now - 2*hour,  "sess-demo-enacted", None,                    json.dumps({"spec_id": "spec-1"}), 24),
            (str(uuid.uuid4()), "SESSION_DEPLOYED",        now - 1*hour,  "sess-demo-enacted", None,                    json.dumps({"deployed": True}), 25),
        ]
        conn.executemany(
            "INSERT INTO event_log "
            "(event_id, event_type, timestamp, session_id, agent_did, payload, sequence_number) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            events,
        )
        conn.commit()
        summary["observatory"] = {"events": len(events)}
    conn.close()

    return {"status": "ok", "seeded": summary}


# ---------------------------------------------------------------------------
# Auth / Identity
# ---------------------------------------------------------------------------


@app.post("/api/users", tags=["Auth"])
async def sign_up(body: SignUpBody):
    """Register a new agent as a user on the platform."""
    result = await _dispatch(
        ActionType.SIGNUP,
        body.agent_id,
        (body.user_name, body.name, body.bio),
    )
    return result


# ---------------------------------------------------------------------------
# Feed
# ---------------------------------------------------------------------------


def _agent_int_from_any(agent_id: str | int) -> int:
    if isinstance(agent_id, int):
        return agent_id
    match = re.search(r"(\d+)$", agent_id)
    if match:
        return int(match.group(1))
    raise ValueError(f"Unsupported OASIS agent id: {agent_id!r}")


def _agent_did_for(agent_id: str, agent_dids: dict[str, str] | None = None) -> str:
    if agent_dids and agent_dids.get(agent_id):
        return agent_dids[agent_id]
    return f"did:mock:{agent_id}"


def _normalize_feed_items(feed_result: Any) -> list[dict[str, Any]]:
    if isinstance(feed_result, list):
        return feed_result
    if isinstance(feed_result, dict):
        items = feed_result.get("items")
        if isinstance(items, list):
            return items
    return []


def _extract_balance(balance_payload: dict[str, Any]) -> float:
    for key in ("balance", "total_balance", "available_balance"):
        value = balance_payload.get(key)
        if value is not None:
            try:
                return float(value)
            except (TypeError, ValueError):
                continue
    return 0.0


async def _build_batch_observation(
    agent_id: str,
    limit: int,
    agent_count: int,
    agent_dids: dict[str, str] | None = None,
) -> tuple[str, dict[str, Any]]:
    did = _agent_did_for(agent_id, agent_dids)
    timestamp_utc = datetime.now(UTC).isoformat()

    try:
        raw_feed = await _dispatch(ActionType.REFRESH, _agent_int_from_any(agent_id))
    except Exception:
        raw_feed = {}

    try:
        mission_board = exec_ep._get_service().list_agent_tasks(did)
    except Exception:
        mission_board = {"agent_did": did, "tasks": []}

    try:
        balance_payload = await adj_ep.get_agent_balance(did)
    except Exception:
        balance_payload = {}

    balance = _extract_balance(balance_payload)
    observation = {
        "schema_version": "2.0.0",
        "round": 0,
        "timestamp_utc": timestamp_utc,
        "agent_id": agent_id,
        "environment": {
            "type": "oasis_social_simulation",
            "state": {
                "current_round": 0,
                "agent_count": agent_count,
                "agent_balance": balance,
            },
            "social_feed": _normalize_feed_items(raw_feed)[:limit],
            "mission_board": mission_board,
            "notifications": [],
        },
        "private_context": {"balance": balance},
    }
    return agent_id, observation


@app.get("/api/feed", tags=["Feed"])
async def refresh(agent_id: int = Query(..., description="Agent ID")):
    """Fetch the recommended post feed for the agent."""
    result = await _dispatch(ActionType.REFRESH, agent_id)
    return result


@app.post("/api/mitosis/observations/batch", tags=["Feed"])
async def batch_observations(body: ObservationBatchBody):
    """Fetch observation payloads for many agents from one server-side snapshot."""
    try:
        summary = obs_ep._get_service().get_summary()
    except Exception:
        summary = {}

    agent_count = sum((summary.get("agents_by_type") or {}).values())
    pairs = await asyncio.gather(
        *[
            _build_batch_observation(
                agent_id=agent_id,
                limit=body.limit,
                agent_count=agent_count,
                agent_dids=body.agent_dids,
            )
            for agent_id in body.agent_ids
        ]
    )
    return {"observations": {agent_id: observation for agent_id, observation in pairs}}


@app.get("/api/trends", tags=["Feed"])
async def trend(agent_id: int = Query(..., description="Agent ID")):
    """Fetch trending topics/posts for the agent."""
    result = await _dispatch(ActionType.TREND, agent_id)
    return result


# ---------------------------------------------------------------------------
# Posts
# ---------------------------------------------------------------------------


@app.post("/api/posts", tags=["Posts"])
async def create_post(body: CreatePostBody):
    """Create a new post."""
    result = await _dispatch(ActionType.CREATE_POST, body.agent_id,
                              body.content)
    return result


@app.post("/api/posts/{post_id}/like", tags=["Posts"])
async def like_post(post_id: int, body: AgentIdBody):
    """Like a post."""
    result = await _dispatch(ActionType.LIKE_POST, body.agent_id, post_id)
    return result


@app.delete("/api/posts/{post_id}/like", tags=["Posts"])
async def unlike_post(post_id: int, body: AgentIdBody):
    """Remove a like from a post."""
    result = await _dispatch(ActionType.UNLIKE_POST, body.agent_id, post_id)
    return result


@app.post("/api/posts/{post_id}/dislike", tags=["Posts"])
async def dislike_post(post_id: int, body: AgentIdBody):
    """Dislike a post."""
    result = await _dispatch(ActionType.DISLIKE_POST, body.agent_id, post_id)
    return result


@app.delete("/api/posts/{post_id}/dislike", tags=["Posts"])
async def undo_dislike_post(post_id: int, body: AgentIdBody):
    """Remove a dislike from a post."""
    result = await _dispatch(ActionType.UNDO_DISLIKE_POST, body.agent_id,
                              post_id)
    return result


@app.post("/api/posts/{post_id}/repost", tags=["Posts"])
async def repost(post_id: int, body: AgentIdBody):
    """Repost an existing post."""
    result = await _dispatch(ActionType.REPOST, body.agent_id, post_id)
    return result


@app.post("/api/posts/{post_id}/report", tags=["Posts"])
async def report_post(post_id: int, body: ReportPostBody):
    """Report a post.

    The Platform's report_post expects ``report_message = (post_id, reason)``.
    """
    result = await _dispatch(ActionType.REPORT_POST, body.agent_id,
                              (post_id, body.reason))
    return result


@app.post("/api/posts/{post_id}/quote", tags=["Posts"])
async def quote_post(post_id: int, body: QuotePostBody):
    """Quote a post with added commentary.

    The Platform's quote_post expects ``quote_message = (post_id, content)``.
    """
    result = await _dispatch(ActionType.QUOTE_POST, body.agent_id,
                              (post_id, body.content))
    return result


# ---------------------------------------------------------------------------
# Comments
# ---------------------------------------------------------------------------


@app.post("/api/posts/{post_id}/comments", tags=["Comments"])
async def create_comment(post_id: int, body: CreateCommentBody):
    """Create a comment on a post.

    The Platform's create_comment expects ``comment_message = (post_id, content)``.
    """
    result = await _dispatch(ActionType.CREATE_COMMENT, body.agent_id,
                              (post_id, body.content))
    return result


@app.post("/api/comments/{comment_id}/like", tags=["Comments"])
async def like_comment(comment_id: int, body: AgentIdBody):
    """Like a comment."""
    result = await _dispatch(ActionType.LIKE_COMMENT, body.agent_id,
                              comment_id)
    return result


@app.delete("/api/comments/{comment_id}/like", tags=["Comments"])
async def unlike_comment(comment_id: int, body: AgentIdBody):
    """Remove a like from a comment."""
    result = await _dispatch(ActionType.UNLIKE_COMMENT, body.agent_id,
                              comment_id)
    return result


@app.post("/api/comments/{comment_id}/dislike", tags=["Comments"])
async def dislike_comment(comment_id: int, body: AgentIdBody):
    """Dislike a comment."""
    result = await _dispatch(ActionType.DISLIKE_COMMENT, body.agent_id,
                              comment_id)
    return result


@app.delete("/api/comments/{comment_id}/dislike", tags=["Comments"])
async def undo_dislike_comment(comment_id: int, body: AgentIdBody):
    """Remove a dislike from a comment."""
    result = await _dispatch(ActionType.UNDO_DISLIKE_COMMENT, body.agent_id,
                              comment_id)
    return result


# ---------------------------------------------------------------------------
# Social Graph
# ---------------------------------------------------------------------------


@app.post("/api/follow", tags=["Social Graph"])
async def follow(body: FollowBody):
    """Follow another user.

    The Platform's follow expects ``followee_id`` as the message.
    """
    result = await _dispatch(ActionType.FOLLOW, body.agent_id,
                              body.target_user_id)
    return result


@app.delete("/api/follow", tags=["Social Graph"])
async def unfollow(body: FollowBody):
    """Unfollow a user."""
    result = await _dispatch(ActionType.UNFOLLOW, body.agent_id,
                              body.target_user_id)
    return result


@app.post("/api/mute", tags=["Social Graph"])
async def mute(body: FollowBody):
    """Mute a user."""
    result = await _dispatch(ActionType.MUTE, body.agent_id,
                              body.target_user_id)
    return result


@app.delete("/api/mute", tags=["Social Graph"])
async def unmute(body: FollowBody):
    """Unmute a user."""
    result = await _dispatch(ActionType.UNMUTE, body.agent_id,
                              body.target_user_id)
    return result


# ---------------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------------


@app.get("/api/search/users", tags=["Search"])
async def search_user(
    agent_id: int = Query(..., description="Agent performing the search"),
    query: str = Query(..., description="Search query string"),
):
    """Search for users by name or username."""
    result = await _dispatch(ActionType.SEARCH_USER, agent_id, query)
    return result


@app.get("/api/search/posts", tags=["Search"])
async def search_posts(
    agent_id: int = Query(..., description="Agent performing the search"),
    query: str = Query(..., description="Search query string"),
):
    """Search for posts by content."""
    result = await _dispatch(ActionType.SEARCH_POSTS, agent_id, query)
    return result


# ---------------------------------------------------------------------------
# Groups
# ---------------------------------------------------------------------------


@app.post("/api/groups", tags=["Groups"])
async def create_group(body: CreateGroupBody):
    """Create a new chat group."""
    result = await _dispatch(ActionType.CREATE_GROUP, body.agent_id,
                              body.group_name)
    return result


@app.post("/api/groups/{group_id}/join", tags=["Groups"])
async def join_group(group_id: int, body: AgentIdBody):
    """Join an existing group."""
    result = await _dispatch(ActionType.JOIN_GROUP, body.agent_id, group_id)
    return result


@app.post("/api/groups/{group_id}/leave", tags=["Groups"])
async def leave_group(group_id: int, body: AgentIdBody):
    """Leave a group."""
    result = await _dispatch(ActionType.LEAVE_GROUP, body.agent_id, group_id)
    return result


@app.post("/api/groups/{group_id}/messages", tags=["Groups"])
async def send_to_group(group_id: int, body: AgentIdWithContentBody):
    """Send a message to a group.

    The Platform's send_to_group expects ``message = (group_id, content)``.
    """
    result = await _dispatch(ActionType.SEND_TO_GROUP, body.agent_id,
                              (group_id, body.content))
    return result


@app.get("/api/groups/listen", tags=["Groups"])
async def listen_from_group(
    agent_id: int = Query(..., description="Agent ID"),
):
    """Listen for messages from all groups the agent belongs to."""
    result = await _dispatch(ActionType.LISTEN_FROM_GROUP, agent_id)
    return result


# ---------------------------------------------------------------------------
# Products
# ---------------------------------------------------------------------------


@app.post("/api/products/{product_name}/purchase", tags=["Products"])
async def purchase_product(product_name: str, body: PurchaseProductBody):
    """Purchase a product.

    The Platform's purchase_product expects
    ``purchase_message = (product_name, quantity)``.
    """
    result = await _dispatch(ActionType.PURCHASE_PRODUCT, body.agent_id,
                              (product_name, body.quantity))
    return result


# ---------------------------------------------------------------------------
# Governance endpoints are now served by oasis.governance.endpoints router
# (included via app.include_router above — replaces previous 501 stubs)
# ---------------------------------------------------------------------------
