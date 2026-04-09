"""Tests for the observatory leaderboard endpoint."""
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


def test_agents_ranked_correctly(client: TestClient, agents):
    """Agents are ranked by reputation_score descending."""
    resp = client.get("/api/observatory/agents/leaderboard")
    assert resp.status_code == 200
    data = resp.json()

    # Should have at least our 3 test agents
    producer_entries = [e for e in data if e["agent_type"] == "producer"]
    assert len(producer_entries) >= 3

    # Check descending reputation order
    scores = [e["reputation_score"] for e in data]
    assert scores == sorted(scores, reverse=True)

    # Rank numbers are sequential
    ranks = [e["rank"] for e in data]
    assert ranks == list(range(1, len(data) + 1))


def test_sortable_by_different_metrics(client: TestClient, agents):
    """Leaderboard can be sorted by total_balance instead of reputation."""
    resp = client.get("/api/observatory/agents/leaderboard?sort_by=total_balance")
    assert resp.status_code == 200
    data = resp.json()

    balances = [e["total_balance"] for e in data]
    assert balances == sorted(balances, reverse=True)
