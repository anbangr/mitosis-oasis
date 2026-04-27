"""P8.1 — Session management API tests."""
from __future__ import annotations

from oasis.governance import endpoints as gov_ep
from oasis.config import PlatformConfig


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


def test_create_session_with_governance_mode(client):
    """POST /sessions stores governance_mode and returns it in response."""
    resp = client.post(
        "/api/governance/sessions",
        json={"mission_budget_cap": 500.0, "governance_mode": "structural"},
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["governance_mode"] == "structural"


def test_create_session_with_milestone_id(client):
    """POST /sessions stores milestone_id and returns it in response."""
    resp = client.post(
        "/api/governance/sessions",
        json={"mission_budget_cap": 500.0, "milestone_id": "milestone-03"},
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["milestone_id"] == "milestone-03"


def test_create_session_governance_mode_none_rejected(client):
    """POST /sessions with governance_mode='none' returns 409."""
    gov_ep.set_platform_config(PlatformConfig(governance_mode="none"))
    try:
        resp = client.post(
            "/api/governance/sessions",
            json={"mission_budget_cap": 500.0, "governance_mode": "none"},
        )
        assert resp.status_code == 409
    finally:
        gov_ep.set_platform_config(PlatformConfig())  # restore default


def test_create_session_invalid_governance_mode_rejected(client):
    """POST /sessions with an unrecognised governance_mode returns 400."""
    resp = client.post(
        "/api/governance/sessions",
        json={"mission_budget_cap": 500.0, "governance_mode": "ultramode"},
    )
    assert resp.status_code == 400


def test_get_session_includes_governance_fields(client):
    """GET /sessions/{id} response includes governance_mode, milestone_id, quality_crisis."""
    resp = client.post(
        "/api/governance/sessions",
        json={"mission_budget_cap": 500.0, "governance_mode": "emergent", "milestone_id": "milestone-01"},
    )
    session_id = resp.json()["session_id"]

    resp = client.get(f"/api/governance/sessions/{session_id}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["governance_mode"] == "emergent"
    assert data["milestone_id"] == "milestone-01"
    assert data["quality_crisis"] is False
