"""Shared fixtures for adjudication tests."""
from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Generator

import pytest

from oasis.config import PlatformConfig
from oasis.governance.schema import (
    create_governance_tables,
    seed_clerks,
    seed_constitution,
)
from oasis.execution.schema import create_execution_tables
from oasis.adjudication.schema import create_adjudication_tables


# ---------------------------------------------------------------------------
# Core DB fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def db_path(tmp_path: Path) -> Path:
    """Fresh temporary SQLite database path."""
    return tmp_path / "test_adjudication.db"


@pytest.fixture()
def adjudication_db(db_path: Path) -> Path:
    """Governance + execution + adjudication tables initialised with seeds."""
    create_governance_tables(db_path)
    seed_constitution(db_path)
    seed_clerks(db_path)
    create_execution_tables(db_path)
    create_adjudication_tables(db_path)
    return db_path


@pytest.fixture()
def db_conn(adjudication_db: Path) -> Generator[sqlite3.Connection, None, None]:
    """Yield a sqlite3 connection with FK enforcement; auto-close."""
    conn = sqlite3.connect(str(adjudication_db))
    conn.execute("PRAGMA foreign_keys = ON")
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()


@pytest.fixture()
def config() -> PlatformConfig:
    """Default platform configuration."""
    return PlatformConfig()


# ---------------------------------------------------------------------------
# Test agent helpers
# ---------------------------------------------------------------------------

ADJ_AGENTS = [
    {
        "agent_did": f"did:adj:agent-{i}",
        "display_name": f"Adj Agent {i}",
        "reputation_score": 0.5,
    }
    for i in range(1, 4)
]


@pytest.fixture()
def agents(adjudication_db: Path) -> list[dict]:
    """Register 3 producer agents for adjudication tests."""
    conn = sqlite3.connect(str(adjudication_db))
    conn.execute("PRAGMA foreign_keys = ON")
    for a in ADJ_AGENTS:
        conn.execute(
            "INSERT OR IGNORE INTO agent_registry "
            "(agent_did, agent_type, display_name, human_principal, reputation_score) "
            "VALUES (?, 'producer', ?, 'human@example.com', ?)",
            (a["agent_did"], a["display_name"], a["reputation_score"]),
        )
        # Ensure agent_balance exists
        conn.execute(
            "INSERT OR IGNORE INTO agent_balance "
            "(agent_did, total_balance, locked_stake, available_balance) "
            "VALUES (?, 100.0, 10.0, 90.0)",
            (a["agent_did"],),
        )
    conn.commit()
    conn.close()
    return list(ADJ_AGENTS)


@pytest.fixture()
def seeded_task(adjudication_db: Path, agents: list[dict]) -> dict:
    """Create a minimal legislative session + proposal + bid + task_assignment for testing.

    Returns dict with session_id, task_id, node_id, agent_did, bid_amount.
    """
    conn = sqlite3.connect(str(adjudication_db))
    conn.execute("PRAGMA foreign_keys = ON")

    agent = agents[0]
    session_id = "adj-sess-001"
    proposal_id = "adj-prop-001"
    node_id = "adj-node-001"
    task_id = "adj-task-001"
    bid_id = "adj-bid-001"

    # Legislative session
    conn.execute(
        "INSERT OR IGNORE INTO legislative_session "
        "(session_id, state, epoch, mission_budget_cap) "
        "VALUES (?, 'DEPLOYED', 0, 1000.0)",
        (session_id,),
    )

    # Proposal
    conn.execute(
        "INSERT OR IGNORE INTO proposal "
        "(proposal_id, session_id, proposer_did, dag_spec, token_budget_total, deadline_ms) "
        "VALUES (?, ?, ?, '{}', 1000.0, 60000)",
        (proposal_id, session_id, agent["agent_did"]),
    )

    # DAG node
    conn.execute(
        "INSERT OR IGNORE INTO dag_node "
        "(node_id, proposal_id, label, service_id, pop_tier, token_budget, timeout_ms) "
        "VALUES (?, ?, 'Test Task', 'test-svc', 1, 200.0, 60000)",
        (node_id, proposal_id),
    )

    # Approved bid
    conn.execute(
        "INSERT OR IGNORE INTO bid "
        "(bid_id, session_id, task_node_id, bidder_did, stake_amount, status) "
        "VALUES (?, ?, ?, ?, 10.0, 'approved')",
        (bid_id, session_id, node_id, agent["agent_did"]),
    )

    # Task assignment
    conn.execute(
        "INSERT OR IGNORE INTO task_assignment "
        "(task_id, session_id, node_id, agent_did, status) "
        "VALUES (?, ?, ?, ?, 'committed')",
        (task_id, session_id, node_id, agent["agent_did"]),
    )

    # Task commitment
    conn.execute(
        "INSERT OR IGNORE INTO task_commitment "
        "(commitment_id, task_id, agent_did, stake_amount) "
        "VALUES ('adj-commit-001', ?, ?, 10.0)",
        (task_id, agent["agent_did"]),
    )

    # Task output
    conn.execute(
        "INSERT OR IGNORE INTO task_output "
        "(output_id, task_id, agent_did, output_data, latency_ms) "
        "VALUES ('adj-out-001', ?, ?, ?, 100)",
        (task_id, agent["agent_did"],
         '{"task_id": "adj-task-001", "result": "ok", "status": "success", '
         '"metrics": {"accuracy": 0.9, "completeness": 0.8}}'),
    )

    # Output validation
    conn.execute(
        "INSERT OR IGNORE INTO output_validation "
        "(validation_id, task_id, schema_valid, timeout_valid, quality_score) "
        "VALUES ('adj-val-001', ?, 1, 1, 0.85)",
        (task_id,),
    )

    conn.commit()
    conn.close()

    return {
        "session_id": session_id,
        "task_id": task_id,
        "node_id": node_id,
        "agent_did": agent["agent_did"],
        "bid_amount": 10.0,
    }
