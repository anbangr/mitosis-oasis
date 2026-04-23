"""Adjudication API endpoint tests (8 tests)."""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from oasis.api import app
from oasis.adjudication import endpoints as adj_ep
from oasis.governance.schema import (
    create_governance_tables,
    seed_clerks,
    seed_constitution,
)
from oasis.execution.schema import create_execution_tables
from oasis.adjudication.schema import create_adjudication_tables


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def adj_db(tmp_path: Path) -> Path:
    """Create a fully initialised DB and wire it into the adjudication endpoints."""
    db = tmp_path / "adj_api_test.db"
    create_governance_tables(db)
    seed_constitution(db)
    seed_clerks(db)
    create_execution_tables(db)
    create_adjudication_tables(db)
    adj_ep.init_adjudication_db(str(db))
    return db


@pytest.fixture()
def client(adj_db: Path) -> TestClient:
    """TestClient without full platform lifespan."""
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture()
def seeded_data(adj_db: Path) -> dict:
    """Seed test data: agents, alerts, flags, decisions, balances, treasury."""
    conn = sqlite3.connect(str(adj_db))
    conn.execute("PRAGMA foreign_keys = ON")

    agent_did = "did:adj-api:agent-1"
    agent_did_2 = "did:adj-api:agent-2"
    session_id = "adj-api-sess-1"
    task_id = "adj-api-task-1"

    # Agents
    conn.execute(
        "INSERT INTO agent_registry "
        "(agent_did, agent_type, display_name, human_principal, reputation_score) "
        "VALUES (?, 'producer', 'API Agent 1', 'human@test.com', 0.5)",
        (agent_did,),
    )
    conn.execute(
        "INSERT INTO agent_registry "
        "(agent_did, agent_type, display_name, human_principal, reputation_score) "
        "VALUES (?, 'producer', 'API Agent 2', 'human@test.com', 0.5)",
        (agent_did_2,),
    )

    # Balance
    conn.execute(
        "INSERT INTO agent_balance "
        "(agent_did, total_balance, locked_stake, available_balance) "
        "VALUES (?, 100.0, 10.0, 90.0)",
        (agent_did,),
    )

    # Session
    conn.execute(
        "INSERT INTO legislative_session "
        "(session_id, state, epoch, mission_budget_cap) "
        "VALUES (?, 'DEPLOYED', 0, 1000.0)",
        (session_id,),
    )

    # Proposal + DAG node (needed for task_assignment FK)
    conn.execute(
        "INSERT INTO proposal "
        "(proposal_id, session_id, proposer_did, dag_spec, token_budget_total, deadline_ms) "
        "VALUES ('adj-api-prop-1', ?, ?, '{}', 1000.0, 60000)",
        (session_id, agent_did),
    )
    conn.execute(
        "INSERT INTO dag_node "
        "(node_id, proposal_id, label, service_id, pop_tier, token_budget, timeout_ms) "
        "VALUES ('adj-api-node-1', 'adj-api-prop-1', 'Test', 'svc', 1, 200.0, 60000)",
    )

    # Task assignment
    conn.execute(
        "INSERT INTO task_assignment "
        "(task_id, session_id, node_id, agent_did, status) "
        "VALUES (?, ?, 'adj-api-node-1', ?, 'committed')",
        (task_id, session_id, agent_did),
    )

    # Guardian alert
    conn.execute(
        "INSERT INTO guardian_alert "
        "(alert_id, task_id, alert_type, severity, details) "
        "VALUES ('test-alert-1', ?, 'quality_below_threshold', 'WARNING', 'quality=0.45')",
        (task_id,),
    )

    # Coordination flag
    conn.execute(
        "INSERT INTO coordination_flag "
        "(flag_id, session_id, agent_did_1, agent_did_2, flag_type, score) "
        "VALUES ('test-flag-1', ?, ?, 'did:adj-api:agent-2', 'voting', 0.95)",
        (session_id, agent_did),
    )

    # Adjudication decision
    conn.execute(
        "INSERT INTO adjudication_decision "
        "(decision_id, alert_id, flag_id, agent_did, decision_type, severity, reason, layer1_result) "
        "VALUES ('test-dec-1', 'test-alert-1', NULL, ?, 'freeze', 'CRITICAL', 'Test freeze', 'FREEZE')",
        (agent_did,),
    )

    # Treasury entries
    conn.execute(
        "INSERT INTO treasury "
        "(task_id, entry_type, amount, balance_after) "
        "VALUES (?, 'protocol_fee', 2.0, 2.0)",
        (task_id,),
    )
    conn.execute(
        "INSERT INTO treasury "
        "(task_id, entry_type, amount, balance_after) "
        "VALUES (?, 'insurance_fee', 1.0, 3.0)",
        (task_id,),
    )

    conn.commit()
    conn.close()

    return {
        "agent_did": agent_did,
        "session_id": session_id,
        "task_id": task_id,
    }


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestAdjudicationAPI:
    """Adjudication REST endpoint tests."""

    def test_list_alerts(self, client, seeded_data):
        """GET /api/adjudication/alerts returns alerts."""
        resp = client.get("/api/adjudication/alerts")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) >= 1
        assert data[0]["alert_id"] == "test-alert-1"

    def test_get_alert_detail(self, client, seeded_data):
        """GET /api/adjudication/alerts/{alert_id} returns alert details."""
        resp = client.get("/api/adjudication/alerts/test-alert-1")
        assert resp.status_code == 200
        assert resp.json()["severity"] == "WARNING"

    def test_get_alert_404(self, client, seeded_data):
        """GET /api/adjudication/alerts/{unknown} returns 404."""
        resp = client.get("/api/adjudication/alerts/nonexistent")
        assert resp.status_code == 404

    def test_list_flags(self, client, seeded_data):
        """GET /api/adjudication/flags returns coordination flags."""
        resp = client.get(
            "/api/adjudication/flags",
            params={"session_id": seeded_data["session_id"]},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) >= 1
        assert data[0]["flag_type"] == "voting"

    def test_list_decisions(self, client, seeded_data):
        """GET /api/adjudication/decisions returns decisions with filters."""
        resp = client.get(
            "/api/adjudication/decisions",
            params={"agent_did": seeded_data["agent_did"]},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) >= 1
        assert data[0]["decision_type"] == "freeze"

    def test_get_decision_detail(self, client, seeded_data):
        """GET /api/adjudication/decisions/{decision_id} returns detail."""
        resp = client.get("/api/adjudication/decisions/test-dec-1")
        assert resp.status_code == 200
        assert resp.json()["layer1_result"] == "FREEZE"

    def test_get_agent_balance(self, client, seeded_data):
        """GET /api/adjudication/agents/{agent_did}/balance returns balance."""
        resp = client.get(
            f"/api/adjudication/agents/{seeded_data['agent_did']}/balance"
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_balance"] == 100.0
        assert data["locked_stake"] == 10.0

    def test_get_agent_balance_initializes_missing_balance(self, client, seeded_data):
        """GET /api/adjudication/agents/{agent_did}/balance creates the default row."""
        agent_did = "did:adj-api:new-agent"
        resp = client.get(f"/api/adjudication/agents/{agent_did}/balance")
        assert resp.status_code == 200
        data = resp.json()
        assert data["agent_did"] == agent_did
        assert data["total_balance"] == 100.0
        assert data["available_balance"] == 100.0

    def test_get_treasury(self, client, seeded_data):
        """GET /api/adjudication/treasury returns summary."""
        resp = client.get("/api/adjudication/treasury")
        assert resp.status_code == 200
        data = resp.json()
        assert data["net_balance"] == 3.0
        assert "protocol_fee" in data["inflows"]

    def test_get_treasury_ledger(self, client, seeded_data):
        """GET /api/adjudication/treasury/ledger returns entries."""
        resp = client.get("/api/adjudication/treasury/ledger")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) >= 2

    def test_v1_list_alerts(self, client, seeded_data):
        """GET /api/v1/adjudication/alerts returns alerts."""
        resp = client.get("/api/v1/adjudication/alerts")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) >= 1
