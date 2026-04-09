"""P8.10 — Constitution & agents API tests."""
from __future__ import annotations


def test_get_params(client, gov_db):
    """GET /constitution returns constitutional parameters."""
    resp = client.get("/api/governance/constitution")
    assert resp.status_code == 200
    data = resp.json()
    assert "parameters" in data
    names = {p["param_name"] for p in data["parameters"]}
    assert "quorum_threshold" in names
    assert "budget_cap_max" in names


def test_list_agents(client, gov_db, registered_producers):
    """GET /agents lists registered agents."""
    resp = client.get("/api/governance/agents")
    assert resp.status_code == 200
    data = resp.json()
    assert "agents" in data
    # Should have clerks + producers
    assert len(data["agents"]) >= 4 + 5


def test_reputation_history(client, gov_db, registered_producers):
    """GET /agents/{did}/reputation returns history (may be empty)."""
    resp = client.get("/api/governance/agents/did:mock:producer-1/reputation")
    assert resp.status_code == 200
    data = resp.json()
    assert data["agent_did"] == "did:mock:producer-1"
    assert "current_score" in data
    assert isinstance(data["history"], list)
