"""P0 — Validate API TestClient fixture can hit the health endpoint."""
import pytest
from fastapi.testclient import TestClient


def test_health_endpoint(client: TestClient):
    """GET /api/health returns 200."""
    resp = client.get("/api/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"


def test_governance_endpoints_available(client: TestClient):
    """Governance endpoints are now live (P8 replaced 501 stubs)."""
    resp = client.get("/api/governance/constitution")
    assert resp.status_code == 200
