"""Shared fixtures for governance tests.

All fixtures create isolated state per test (tmp_path) so tests never
interfere with each other.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Generator

import pytest

from oasis.governance.schema import (
    create_governance_tables,
    seed_clerks,
    seed_constitution,
)


# ---------------------------------------------------------------------------
# Core database fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def db_path(tmp_path: Path) -> Path:
    """Return a fresh temporary SQLite database path (auto-cleaned)."""
    return tmp_path / "test_governance.db"


@pytest.fixture()
def governance_db(db_path: Path) -> Path:
    """Initialised governance database with tables + seeds.

    Returns the db_path after calling ``create_governance_tables``,
    ``seed_constitution``, and ``seed_clerks``.
    """
    create_governance_tables(db_path)
    seed_constitution(db_path)
    seed_clerks(db_path)
    return db_path


# ---------------------------------------------------------------------------
# Sample data fixtures
# ---------------------------------------------------------------------------

SAMPLE_PRODUCER_AGENTS = [
    {
        "agent_did": f"did:mock:producer-{i}",
        "agent_type": "producer",
        "display_name": f"Producer Agent {i}",
        "human_principal": f"human-{i}@example.com",
        "reputation_score": 0.5,
    }
    for i in range(1, 6)
]

SAMPLE_CLERK_ROLES = ["registrar", "speaker", "regulator", "codifier"]

SAMPLE_CLERK_AGENTS = [
    {
        "agent_did": f"did:mock:clerk-{role}",
        "agent_type": "clerk",
        "display_name": f"Clerk ({role.title()})",
        "human_principal": "platform@metosis.dev",
        "clerk_role": role,
        "authority_envelope": json.dumps({
            "role": role,
            "permissions": [f"{role}:*"],
            "issued_at": "2026-01-01T00:00:00Z",
        }),
    }
    for role in SAMPLE_CLERK_ROLES
]

SAMPLE_CONSTITUTION_PARAMS = {
    "budget_cap_max": 1_000_000.0,
    "budget_cap_min": 1.0,
    "quorum_threshold": 0.51,
    "max_deliberation_rounds": 3,
    "reputation_floor": 0.1,
    "fairness_hhi_threshold": 0.25,
    "proposal_deadline_max_ms": 86_400_000,
    "voting_method": 1.0,  # 1 = Copeland
    "max_dag_depth": 10,
    "max_dag_nodes": 50,
}

SAMPLE_DAG = {
    "nodes": [
        {"node_id": "root", "label": "Coordinate", "service_id": "coordinator",
         "pop_tier": 1, "token_budget": 100.0, "timeout_ms": 60000},
        {"node_id": "task-a", "label": "Data Collection", "service_id": "scraper",
         "pop_tier": 2, "token_budget": 200.0, "timeout_ms": 120000},
        {"node_id": "task-b", "label": "Analysis", "service_id": "analyzer",
         "pop_tier": 2, "token_budget": 300.0, "timeout_ms": 180000},
    ],
    "edges": [
        {"from_node_id": "root", "to_node_id": "task-a"},
        {"from_node_id": "root", "to_node_id": "task-b"},
    ],
}


@pytest.fixture()
def sample_agents() -> dict:
    """Return dicts for 5 producer agents + 4 clerk agents."""
    return {
        "producers": SAMPLE_PRODUCER_AGENTS,
        "clerks": SAMPLE_CLERK_AGENTS,
    }


@pytest.fixture()
def sample_constitution() -> dict:
    """Default constitutional parameters."""
    return dict(SAMPLE_CONSTITUTION_PARAMS)


@pytest.fixture()
def sample_dag() -> dict:
    """A simple 3-node DAG (1 root → 2 tasks) for reuse in tests."""
    return json.loads(json.dumps(SAMPLE_DAG))  # deep copy


# ---------------------------------------------------------------------------
# DB connection helper
# ---------------------------------------------------------------------------

@pytest.fixture()
def db_conn(governance_db: Path) -> Generator[sqlite3.Connection, None, None]:
    """Yield a sqlite3 connection to the governance DB; auto-close."""
    conn = sqlite3.connect(str(governance_db))
    conn.execute("PRAGMA foreign_keys = ON")
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()
