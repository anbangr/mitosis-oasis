# =========== Copyright 2023 @ CAMEL-AI.org. All Rights Reserved. ===========
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
# =========== Copyright 2023 @ CAMEL-AI.org. All Rights Reserved. ===========
"""Admin endpoint authentication tests.

Covers _require_admin dependency — missing token (401), wrong token (403),
correct token (201/200 pass-through).
"""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from oasis.api import app
from oasis.admin import endpoints as admin_ep
from oasis.governance import endpoints as gov_ep


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def gov_db(tmp_path: Path) -> Path:
    gov_ep.init_governance_db(str(tmp_path / "auth_gov_test.db"))
    return tmp_path / "auth_gov_test.db"


@pytest.fixture()
def authed_client(gov_db: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    """Client fixture with ADMIN_TOKEN set to a known value."""
    monkeypatch.setattr(admin_ep, "_ADMIN_TOKEN", "test-secret-token")
    admin_ep.set_admin_db(str(gov_db))
    return TestClient(app, raise_server_exceptions=False)


_BULK_PAYLOAD = {
    "agents": [
        {
            "agent_did": "did:auth:test-1",
            "agent_type": "producer",
            "capability_tier": "t1",
            "display_name": "Auth Test Agent",
            "reputation_score": 0.5,
        }
    ]
}


# ---------------------------------------------------------------------------
# Auth tests
# ---------------------------------------------------------------------------


def test_missing_token_returns_401(authed_client):
    """POST /agents/bulk without X-Admin-Token returns 401."""
    resp = authed_client.post("/api/v1/admin/agents/bulk", json=_BULK_PAYLOAD)
    assert resp.status_code == 401


def test_wrong_token_returns_403(authed_client):
    """POST /agents/bulk with wrong X-Admin-Token returns 403."""
    resp = authed_client.post(
        "/api/v1/admin/agents/bulk",
        json=_BULK_PAYLOAD,
        headers={"X-Admin-Token": "wrong-token"},
    )
    assert resp.status_code == 403


def test_correct_token_passes(authed_client):
    """POST /agents/bulk with correct X-Admin-Token returns 201."""
    resp = authed_client.post(
        "/api/v1/admin/agents/bulk",
        json=_BULK_PAYLOAD,
        headers={"X-Admin-Token": "test-secret-token"},
    )
    assert resp.status_code == 201
    assert resp.json()["registered"] == 1


def test_unversioned_prefix_also_enforces_auth(authed_client):
    """POST /api/admin/agents/bulk (unversioned) also enforces auth."""
    resp = authed_client.post("/api/admin/agents/bulk", json=_BULK_PAYLOAD)
    assert resp.status_code == 401


def test_shock_endpoint_enforces_auth(authed_client):
    """POST /api/v1/admin/shock without token returns 401."""
    resp = authed_client.post(
        "/api/v1/admin/shock",
        json={"free_rider_count": 1, "coalition_size": 0, "high_rep_remove_count": 0},
    )
    assert resp.status_code == 401
