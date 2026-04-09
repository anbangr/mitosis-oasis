"""Test the POST /api/seed-demo endpoint.

Verifies that seeding populates data across all branches and that
observatory endpoints return meaningful content after seeding.
"""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from oasis.api import app
from oasis.governance.endpoints import init_governance_db
from oasis.execution.endpoints import init_execution_db
from oasis.execution.schema import create_execution_tables
from oasis.adjudication.endpoints import init_adjudication_db
from oasis.adjudication.schema import create_adjudication_tables
from oasis.observatory.endpoints import init_observatory_db


@pytest.fixture()
def seeded_client(tmp_path: Path) -> TestClient:
    """Return a TestClient with all 4 databases initialised."""
    gov_db = str(tmp_path / "gov.db")
    exec_db = str(tmp_path / "exec.db")
    adj_db = str(tmp_path / "adj.db")
    obs_db = str(tmp_path / "obs.db")

    init_governance_db(gov_db)
    create_execution_tables(exec_db)
    init_execution_db(exec_db)
    create_adjudication_tables(adj_db)
    init_adjudication_db(adj_db)
    init_observatory_db(obs_db)

    return TestClient(app, raise_server_exceptions=True)


def test_seed_demo_creates_data(seeded_client: TestClient):
    """POST /api/seed-demo populates demo data and returns a summary."""
    resp = seeded_client.post("/api/seed-demo")
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["status"] == "ok"
    assert "seeded" in data
    seeded = data["seeded"]
    # Governance should have seeded agents, sessions, reputation entries
    assert isinstance(seeded.get("governance"), dict)
    assert seeded["governance"]["agents"] == 8
    assert seeded["governance"]["sessions"] == 3
    # Execution
    assert isinstance(seeded.get("execution"), dict)
    assert seeded["execution"]["task_assignments"] == 5
    # Adjudication
    assert isinstance(seeded.get("adjudication"), dict)
    assert seeded["adjudication"]["guardian_alerts"] == 2
    assert seeded["adjudication"]["treasury_entries"] == 5
    # Observatory
    assert isinstance(seeded.get("observatory"), dict)
    assert seeded["observatory"]["events"] >= 20


def test_seed_demo_is_idempotent(seeded_client: TestClient):
    """Calling POST /api/seed-demo twice returns 'already seeded'."""
    resp1 = seeded_client.post("/api/seed-demo")
    assert resp1.status_code == 200
    resp2 = seeded_client.post("/api/seed-demo")
    assert resp2.status_code == 200
    data2 = resp2.json()
    assert data2["seeded"]["governance"] == "already seeded"
    assert data2["seeded"]["observatory"] == "already seeded"


def test_observatory_events_after_seed(seeded_client: TestClient):
    """GET /api/observatory/events returns data after seeding."""
    seeded_client.post("/api/seed-demo")
    resp = seeded_client.get("/api/observatory/events")
    assert resp.status_code == 200
    events = resp.json()
    assert len(events) >= 20


def test_observatory_summary_after_seed(seeded_client: TestClient):
    """GET /api/observatory/summary returns populated fields after seeding."""
    seeded_client.post("/api/seed-demo")
    resp = seeded_client.get("/api/observatory/summary")
    assert resp.status_code == 200
    data = resp.json()
    # Should have sessions by state
    assert len(data["sessions_by_state"]) > 0
    # Should have agents by type
    assert len(data["agents_by_type"]) > 0
    # Treasury balance
    assert data["treasury_balance"] > 0
    # Active alerts
    assert data["active_alerts"] >= 2


def test_observatory_leaderboard_after_seed(seeded_client: TestClient):
    """GET /api/observatory/agents/leaderboard returns agents after seeding."""
    seeded_client.post("/api/seed-demo")
    resp = seeded_client.get("/api/observatory/agents/leaderboard")
    assert resp.status_code == 200
    agents = resp.json()
    assert len(agents) == 8
    # Check that agents are sorted by reputation_score descending
    scores = [a["reputation_score"] for a in agents]
    assert scores == sorted(scores, reverse=True)
