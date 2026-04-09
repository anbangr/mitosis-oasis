"""P8.1 — Session management API tests."""
from __future__ import annotations


def test_create_session(client):
    """POST /sessions creates a new session in SESSION_INIT state."""
    resp = client.post(
        "/api/governance/sessions",
        json={"mission_budget_cap": 500.0, "min_reputation": 0.2},
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["state"] == "SESSION_INIT"
    assert "session_id" in data


def test_get_session_state(client):
    """GET /sessions/{id} returns session details."""
    resp = client.post(
        "/api/governance/sessions",
        json={"mission_budget_cap": 500.0},
    )
    session_id = resp.json()["session_id"]

    resp = client.get(f"/api/governance/sessions/{session_id}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["session_id"] == session_id
    assert data["state"] == "SESSION_INIT"


def test_get_session_messages(client):
    """GET /sessions/{id}/messages returns message log."""
    resp = client.post(
        "/api/governance/sessions",
        json={"mission_budget_cap": 500.0},
    )
    session_id = resp.json()["session_id"]

    resp = client.get(f"/api/governance/sessions/{session_id}/messages")
    assert resp.status_code == 200
    data = resp.json()
    assert data["session_id"] == session_id
    assert isinstance(data["messages"], list)


def test_invalid_session_404(client):
    """GET /sessions/{nonexistent} returns 404."""
    resp = client.get("/api/governance/sessions/nonexistent-session")
    assert resp.status_code == 404
