"""Tests for the observatory summary endpoint."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from fastapi import FastAPI

from oasis.observatory.endpoints import router, init_observatory_db


@pytest.fixture()
def client(observatory_db) -> TestClient:
    """FastAPI test client with observatory router."""
    app = FastAPI()
    app.include_router(router)
    init_observatory_db(str(observatory_db))
    return TestClient(app)


def test_summary_correct_aggregates(client: TestClient, seeded_session):
    """Summary returns correct aggregate counts for seeded data."""
    resp = client.get("/api/observatory/summary")
    assert resp.status_code == 200
    data = resp.json()

    # We have 1 DEPLOYED session
    assert data["sessions_by_state"]["DEPLOYED"] >= 1
    # We have agents registered (3 producers + clerks from seed)
    total_agents = sum(data["agents_by_type"].values())
    assert total_agents >= 3
    # 1 task in executing state
    assert data["tasks_in_progress"] >= 1
    # Treasury has a balance
    assert data["treasury_balance"] == 5.0
    # No guardian alerts in seeded data
    assert data["active_alerts"] == 0


def test_empty_db_returns_zeros(observatory_db):
    """Summary endpoint on a mostly-empty DB returns sensible zero values."""
    app = FastAPI()
    app.include_router(router)
    init_observatory_db(str(observatory_db))
    client = TestClient(app)

    resp = client.get("/api/observatory/summary")
    assert resp.status_code == 200
    data = resp.json()

    assert data["tasks_in_progress"] == 0
    assert data["treasury_balance"] == 0.0
    assert data["active_alerts"] == 0
