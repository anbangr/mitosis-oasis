"""Tests for observatory timeseries endpoints."""
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


def test_reputation_timeseries_returns_data(client: TestClient, seeded_session):
    """Reputation timeseries returns data points from the reputation_ledger."""
    resp = client.get("/api/observatory/reputation/timeseries")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) >= 1

    entry = data[0]
    assert "agent_did" in entry
    assert "new_score" in entry
    assert "old_score" in entry
    assert entry["new_score"] == 0.6
    assert entry["old_score"] == 0.5


def test_treasury_timeseries_running_balance(client: TestClient, seeded_session):
    """Treasury timeseries computes running balance over time."""
    resp = client.get("/api/observatory/treasury/timeseries")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) >= 1

    entry = data[0]
    assert "balance_after" in entry
    assert "amount" in entry
    assert entry["balance_after"] == 5.0
    assert entry["amount"] == 5.0
