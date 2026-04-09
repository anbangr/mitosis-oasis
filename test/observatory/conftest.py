"""Shared fixtures for observatory tests."""
from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Generator

import pytest

from oasis.governance.schema import create_governance_tables, seed_clerks, seed_constitution
from oasis.execution.schema import create_execution_tables
from oasis.adjudication.schema import create_adjudication_tables
from oasis.observatory.schema import create_observatory_tables
from oasis.observatory.event_bus import EventBus
from oasis.observatory.events import Event, EventType


# ---------------------------------------------------------------------------
# Core DB fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def db_path(tmp_path: Path) -> Path:
    """Fresh temporary SQLite database path."""
    return tmp_path / "test_observatory.db"


@pytest.fixture()
def observatory_db(db_path: Path) -> Path:
    """Governance + execution + adjudication + observatory tables initialised."""
    create_governance_tables(db_path)
    seed_constitution(db_path)
    seed_clerks(db_path)
    create_execution_tables(db_path)
    create_adjudication_tables(db_path)
    create_observatory_tables(db_path)
    return db_path


@pytest.fixture()
def db_conn(observatory_db: Path) -> Generator[sqlite3.Connection, None, None]:
    """Yield a sqlite3 connection with FK enforcement; auto-close."""
    conn = sqlite3.connect(str(observatory_db))
    conn.execute("PRAGMA foreign_keys = ON")
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()


@pytest.fixture()
def event_bus(observatory_db: Path) -> Generator[EventBus, None, None]:
    """Fresh EventBus instance (resets singleton)."""
    EventBus.reset()
    bus = EventBus(str(observatory_db))
    yield bus
    EventBus.reset()


# ---------------------------------------------------------------------------
# Test data helpers
# ---------------------------------------------------------------------------

OBS_AGENTS = [
    {
        "agent_did": f"did:obs:agent-{i}",
        "display_name": f"Obs Agent {i}",
        "reputation_score": 0.5 + i * 0.1,
    }
    for i in range(1, 4)
]


@pytest.fixture()
def agents(observatory_db: Path) -> list[dict]:
    """Register 3 producer agents with balances."""
    conn = sqlite3.connect(str(observatory_db))
    conn.execute("PRAGMA foreign_keys = ON")
    for a in OBS_AGENTS:
        conn.execute(
            "INSERT OR IGNORE INTO agent_registry "
            "(agent_did, agent_type, display_name, human_principal, reputation_score) "
            "VALUES (?, 'producer', ?, 'human@example.com', ?)",
            (a["agent_did"], a["display_name"], a["reputation_score"]),
        )
        conn.execute(
            "INSERT OR IGNORE INTO agent_balance "
            "(agent_did, total_balance, locked_stake, available_balance) "
            "VALUES (?, 100.0, 10.0, 90.0)",
            (a["agent_did"],),
        )
    conn.commit()
    conn.close()
    return list(OBS_AGENTS)


@pytest.fixture()
def seeded_session(observatory_db: Path, agents: list[dict]) -> dict:
    """Create a legislative session + tasks for observatory testing."""
    conn = sqlite3.connect(str(observatory_db))
    conn.execute("PRAGMA foreign_keys = ON")

    session_id = "obs-sess-001"
    agent = agents[0]

    conn.execute(
        "INSERT OR IGNORE INTO legislative_session "
        "(session_id, state, epoch, mission_budget_cap) "
        "VALUES (?, 'DEPLOYED', 0, 1000.0)",
        (session_id,),
    )

    # Proposal + DAG node + bid + task assignment
    conn.execute(
        "INSERT OR IGNORE INTO proposal "
        "(proposal_id, session_id, proposer_did, dag_spec, token_budget_total, deadline_ms) "
        "VALUES ('obs-prop-001', ?, ?, '{}', 500.0, 60000)",
        (session_id, agent["agent_did"]),
    )
    conn.execute(
        "INSERT OR IGNORE INTO dag_node "
        "(node_id, proposal_id, label, service_id, pop_tier, token_budget, timeout_ms) "
        "VALUES ('obs-node-001', 'obs-prop-001', 'Test Task', 'svc-1', 1, 200.0, 60000)",
    )
    conn.execute(
        "INSERT OR IGNORE INTO bid "
        "(bid_id, session_id, task_node_id, bidder_did, stake_amount, status) "
        "VALUES ('obs-bid-001', ?, 'obs-node-001', ?, 10.0, 'approved')",
        (session_id, agent["agent_did"]),
    )
    conn.execute(
        "INSERT OR IGNORE INTO task_assignment "
        "(task_id, session_id, node_id, agent_did, status) "
        "VALUES ('obs-task-001', ?, 'obs-node-001', ?, 'executing')",
        (session_id, agent["agent_did"]),
    )

    # Reputation ledger entry
    conn.execute(
        "INSERT INTO reputation_ledger "
        "(entry_id, agent_did, old_score, new_score, performance_score, lambda, reason) "
        "VALUES (1, ?, 0.5, 0.6, 0.85, 0.3, 'task completion')",
        (agent["agent_did"],),
    )

    # Treasury entry
    conn.execute(
        "INSERT INTO treasury (task_id, agent_did, entry_type, amount, balance_after) "
        "VALUES ('obs-task-001', ?, 'protocol_fee', 5.0, 5.0)",
        (agent["agent_did"],),
    )

    conn.commit()
    conn.close()

    return {"session_id": session_id, "agent_did": agent["agent_did"]}
