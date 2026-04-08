"""P0 — Validate API TestClient fixture can hit the health endpoint."""
import pytest
from fastapi.testclient import TestClient


def test_health_endpoint(client: TestClient):
    """GET /api/health returns 200."""
    resp = client.get("/api/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"


def test_governance_stub_returns_501(client: TestClient):
    """Governance stubs return 501 until implemented."""
    resp = client.post("/api/governance/proposals")
    assert resp.status_code == 501
