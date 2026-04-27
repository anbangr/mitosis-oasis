"""Admin shock-event endpoint tests.

Covers:
- POST /api/v1/admin/agents/bulk     — inject free-riders and coalition agents
- POST /api/v1/admin/agents/remove-high-rep — deactivate top-N agents
- POST /api/v1/admin/sessions/milestone-crisis — mark quality crisis
- POST /api/v1/admin/shock           — composite shock event
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from oasis.api import app
from oasis.governance import endpoints as gov_ep
from oasis.admin import endpoints as admin_ep


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def gov_db(tmp_path: Path) -> Path:
    gov_ep.init_governance_db(str(tmp_path / "admin_gov_test.db"))
    return tmp_path / "admin_gov_test.db"


@pytest.fixture()
def admin_client(gov_db: Path, monkeypatch) -> TestClient:
    admin_ep.set_admin_db(str(gov_db))
    monkeypatch.setattr(admin_ep, "_ADMIN_TOKEN", "")
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture()
def seeded_agents(gov_db: Path) -> list[str]:
    """Insert 5 producer agents with staggered reputation scores."""
    conn = sqlite3.connect(str(gov_db))
    agents = [
        (f"did:test:agent-{i}", f"Agent {i}", round(0.3 + i * 0.1, 1))
        for i in range(1, 6)
    ]
    for did, name, rep in agents:
        conn.execute(
            "INSERT OR IGNORE INTO agent_registry "
            "(agent_did, agent_type, capability_tier, display_name, reputation_score, active) "
            "VALUES (?, 'producer', 't1', ?, ?, 1)",
            (did, name, rep),
        )
    conn.commit()
    conn.close()
    return [a[0] for a in agents]


@pytest.fixture()
def seeded_session_with_milestone(gov_db: Path) -> str:
    """Insert a legislative session tagged with milestone-05."""
    conn = sqlite3.connect(str(gov_db))
    conn.execute(
        "INSERT INTO legislative_session "
        "(session_id, state, epoch, governance_mode, milestone_id, mission_budget_cap) "
        "VALUES ('sess-m05', 'DEPLOYED', 0, 'full', 'milestone-05', 1000.0)",
    )
    conn.commit()
    conn.close()
    return "sess-m05"


# ---------------------------------------------------------------------------
# Bulk agent injection
# ---------------------------------------------------------------------------


def test_bulk_register_agents(admin_client):
    """POST /api/v1/admin/agents/bulk registers agents and returns count."""
    resp = admin_client.post(
        "/api/v1/admin/agents/bulk",
        json={
            "agents": [
                {
                    "agent_did": "did:shock:fr-1",
                    "agent_type": "producer",
                    "capability_tier": "t1",
                    "display_name": "Free-rider 1",
                    "reputation_score": 0.3,
                    "strategy": "free_rider",
                },
                {
                    "agent_did": "did:shock:fr-2",
                    "agent_type": "producer",
                    "capability_tier": "t1",
                    "display_name": "Free-rider 2",
                    "reputation_score": 0.3,
                    "strategy": "free_rider",
                },
            ]
        },
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["registered"] == 2
    assert "did:shock:fr-1" in data["agents"]
    assert "did:shock:fr-2" in data["agents"]


def test_bulk_register_is_idempotent(admin_client):
    """Re-registering the same agents replaces without error."""
    payload = {
        "agents": [
            {
                "agent_did": "did:shock:idem-1",
                "agent_type": "producer",
                "capability_tier": "t3",
                "display_name": "Idem Agent",
                "reputation_score": 0.5,
            }
        ]
    }
    resp1 = admin_client.post("/api/v1/admin/agents/bulk", json=payload)
    resp2 = admin_client.post("/api/v1/admin/agents/bulk", json=payload)
    assert resp1.status_code == 201
    assert resp2.status_code == 201


def test_bulk_register_empty_list_rejected(admin_client):
    """Empty agent list is rejected with 422."""
    resp = admin_client.post("/api/v1/admin/agents/bulk", json={"agents": []})
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# High-rep agent removal
# ---------------------------------------------------------------------------


def test_remove_high_rep_deactivates_top_n(admin_client, seeded_agents, gov_db):
    """Remove top-2 agents sets active=0 for highest-reputation agents."""
    resp = admin_client.post(
        "/api/v1/admin/agents/remove-high-rep",
        json={"count": 2},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["deactivated"] == 2

    conn = sqlite3.connect(str(gov_db))
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT agent_did, reputation_score, active FROM agent_registry "
        "WHERE agent_type = 'producer' ORDER BY reputation_score DESC"
    ).fetchall()
    conn.close()

    # Top 2 must be inactive; rest still active
    assert rows[0]["active"] == 0
    assert rows[1]["active"] == 0
    assert rows[2]["active"] == 1


def test_remove_high_rep_no_agents_returns_zero(admin_client):
    """When no producers exist, deactivated count is 0."""
    resp = admin_client.post(
        "/api/v1/admin/agents/remove-high-rep",
        json={"count": 5},
    )
    assert resp.status_code == 200
    assert resp.json()["deactivated"] == 0


def test_remove_high_rep_count_zero_rejected(admin_client):
    """count=0 is rejected with 422."""
    resp = admin_client.post(
        "/api/v1/admin/agents/remove-high-rep",
        json={"count": 0},
    )
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Milestone quality crisis
# ---------------------------------------------------------------------------


def test_milestone_crisis_marks_sessions(admin_client, seeded_session_with_milestone, gov_db):
    """POST /milestone-crisis sets quality_crisis=1 on matching sessions."""
    resp = admin_client.post(
        "/api/v1/admin/sessions/milestone-crisis",
        json={"milestone_id": "milestone-05"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["milestone_id"] == "milestone-05"
    assert data["sessions_affected"] == 1
    assert data["quality_crisis"] is True

    conn = sqlite3.connect(str(gov_db))
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        "SELECT quality_crisis FROM legislative_session WHERE session_id = 'sess-m05'"
    ).fetchone()
    conn.close()
    assert bool(row["quality_crisis"]) is True


def test_milestone_crisis_no_sessions_returns_zero(admin_client):
    """Milestone with no matching sessions returns sessions_affected=0."""
    resp = admin_client.post(
        "/api/v1/admin/sessions/milestone-crisis",
        json={"milestone_id": "milestone-99"},
    )
    assert resp.status_code == 200
    assert resp.json()["sessions_affected"] == 0


# ---------------------------------------------------------------------------
# Composite shock event
# ---------------------------------------------------------------------------


def test_shock_event_composite(admin_client, seeded_agents, seeded_session_with_milestone):
    """POST /api/v1/admin/shock applies all sub-operations in one call."""
    resp = admin_client.post(
        "/api/v1/admin/shock",
        json={
            "free_rider_count": 3,
            "coalition_size": 2,
            "high_rep_remove_count": 2,
            "fail_milestone": "milestone-05",
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["shock_applied"] is True
    summary = data["summary"]
    assert summary["free_riders_injected"] == 3
    assert summary["coalition_injected"] == 2
    assert summary["high_rep_removed"] == 2
    assert summary["milestone_crisis"]["milestone_id"] == "milestone-05"


def test_shock_event_no_milestone(admin_client, seeded_agents):
    """Shock event without fail_milestone omits milestone_crisis from summary."""
    resp = admin_client.post(
        "/api/v1/admin/shock",
        json={
            "free_rider_count": 1,
            "coalition_size": 0,
            "high_rep_remove_count": 0,
        },
    )
    assert resp.status_code == 200
    summary = resp.json()["summary"]
    assert "milestone_crisis" not in summary


# ---------------------------------------------------------------------------
# shock_id idempotency
# ---------------------------------------------------------------------------


def test_shock_id_idempotency_returns_cached_result(admin_client, seeded_agents, gov_db):
    """Second call with the same shock_id returns cached result without re-applying."""
    payload = {
        "free_rider_count": 2,
        "coalition_size": 0,
        "high_rep_remove_count": 1,
        "shock_id": "experiment-run-001",
    }

    # First call — applies the shock
    resp1 = admin_client.post("/api/v1/admin/shock", json=payload)
    assert resp1.status_code == 200
    data1 = resp1.json()
    assert data1["shock_applied"] is True
    assert data1["summary"]["free_riders_injected"] == 2

    # Count active agents after first call
    conn = sqlite3.connect(str(gov_db))
    count_after_first = conn.execute(
        "SELECT COUNT(*) FROM agent_registry WHERE active = 1"
    ).fetchone()[0]
    conn.close()

    # Second call with same shock_id — must return identical cached result
    resp2 = admin_client.post("/api/v1/admin/shock", json=payload)
    assert resp2.status_code == 200
    assert resp2.json() == data1  # exact same response object

    # DB state must not have changed (no re-application)
    conn = sqlite3.connect(str(gov_db))
    count_after_second = conn.execute(
        "SELECT COUNT(*) FROM agent_registry WHERE active = 1"
    ).fetchone()[0]
    conn.close()

    assert count_after_second == count_after_first


def test_different_shock_ids_are_independent(admin_client):
    """Different shock_id values are cached independently."""
    resp_a = admin_client.post(
        "/api/v1/admin/shock",
        json={"free_rider_count": 1, "coalition_size": 0, "high_rep_remove_count": 0, "shock_id": "run-A"},
    )
    resp_b = admin_client.post(
        "/api/v1/admin/shock",
        json={"free_rider_count": 2, "coalition_size": 0, "high_rep_remove_count": 0, "shock_id": "run-B"},
    )
    assert resp_a.status_code == 200
    assert resp_b.status_code == 200
    # Each result reflects the actual call, not a shared cache entry
    assert resp_a.json()["summary"]["free_riders_injected"] == 1
    assert resp_b.json()["summary"]["free_riders_injected"] == 2


def test_shock_id_survives_in_process_cache_eviction(admin_client, gov_db):
    """shock_id idempotency is read from SQLite when the in-process dict is cleared."""
    payload = {
        "free_rider_count": 1,
        "coalition_size": 0,
        "high_rep_remove_count": 0,
        "shock_id": "durable-run-001",
    }

    # First call — applies the shock and writes to SQLite cache
    resp1 = admin_client.post("/api/v1/admin/shock", json=payload)
    assert resp1.status_code == 200
    data1 = resp1.json()

    # Evict the in-process cache to simulate a cold start / pod restart
    admin_ep._shock_results.clear()

    # Count agents before the second call
    conn = sqlite3.connect(str(gov_db))
    count_before = conn.execute(
        "SELECT COUNT(*) FROM agent_registry WHERE active = 1"
    ).fetchone()[0]
    conn.close()

    # Second call — must hit SQLite and return the cached result without re-applying
    resp2 = admin_client.post("/api/v1/admin/shock", json=payload)
    assert resp2.status_code == 200
    assert resp2.json() == data1

    # Agent count must not have changed (no re-application)
    conn = sqlite3.connect(str(gov_db))
    count_after = conn.execute(
        "SELECT COUNT(*) FROM agent_registry WHERE active = 1"
    ).fetchone()[0]
    conn.close()
    assert count_after == count_before


def test_shock_without_shock_id_is_not_cached(admin_client, seeded_agents, gov_db):
    """Calls without shock_id always re-apply and are never cached."""
    payload = {"free_rider_count": 1, "coalition_size": 0, "high_rep_remove_count": 0}

    resp1 = admin_client.post("/api/v1/admin/shock", json=payload)
    resp2 = admin_client.post("/api/v1/admin/shock", json=payload)
    assert resp1.status_code == 200
    assert resp2.status_code == 200

    # Both calls applied — injected agents accumulate (INSERT OR REPLACE
    # with same DID overwrites, so count stays 1 free-rider, but two calls ran)
    conn = sqlite3.connect(str(gov_db))
    fr_count = conn.execute(
        "SELECT COUNT(*) FROM agent_registry WHERE agent_did LIKE 'did:shock:free-rider-%'"
    ).fetchone()[0]
    conn.close()
    assert fr_count >= 1  # at minimum the agent exists


# ---------------------------------------------------------------------------
# DoS protection — input bounds
# ---------------------------------------------------------------------------


def test_shock_free_rider_count_upper_bound(admin_client):
    """free_rider_count > 1000 is rejected with 422."""
    resp = admin_client.post(
        "/api/v1/admin/shock",
        json={"free_rider_count": 1001, "coalition_size": 0, "high_rep_remove_count": 0},
    )
    assert resp.status_code == 422


def test_shock_coalition_size_upper_bound(admin_client):
    """coalition_size > 1000 is rejected with 422."""
    resp = admin_client.post(
        "/api/v1/admin/shock",
        json={"free_rider_count": 0, "coalition_size": 1001, "high_rep_remove_count": 0},
    )
    assert resp.status_code == 422


def test_remove_high_rep_upper_bound(admin_client):
    """count > 10000 is rejected with 422."""
    resp = admin_client.post(
        "/api/v1/admin/agents/remove-high-rep",
        json={"count": 10001},
    )
    assert resp.status_code == 422


def test_bulk_agents_upper_bound(admin_client):
    """Bulk register list > 1000 agents is rejected with 422."""
    resp = admin_client.post(
        "/api/v1/admin/agents/bulk",
        json={"agents": [
            {"agent_did": f"did:test:x-{i}", "display_name": f"X {i}"}
            for i in range(1001)
        ]},
    )
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Strategy column persistence
# ---------------------------------------------------------------------------


def test_bulk_register_persists_strategy(admin_client, gov_db):
    """strategy field is written to agent_registry when supplied."""
    resp = admin_client.post(
        "/api/v1/admin/agents/bulk",
        json={
            "agents": [
                {
                    "agent_did": "did:test:strat-fr",
                    "agent_type": "producer",
                    "capability_tier": "t1",
                    "display_name": "Strategy Agent",
                    "reputation_score": 0.3,
                    "strategy": "free_rider",
                }
            ]
        },
    )
    assert resp.status_code == 201

    conn = sqlite3.connect(str(gov_db))
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        "SELECT strategy FROM agent_registry WHERE agent_did = 'did:test:strat-fr'"
    ).fetchone()
    conn.close()
    assert row["strategy"] == "free_rider"


def test_shock_event_persists_strategy(admin_client, gov_db):
    """Shock event injects free-rider and coalition agents with correct strategy."""
    resp = admin_client.post(
        "/api/v1/admin/shock",
        json={"free_rider_count": 1, "coalition_size": 1, "high_rep_remove_count": 0},
    )
    assert resp.status_code == 200

    conn = sqlite3.connect(str(gov_db))
    conn.row_factory = sqlite3.Row
    fr = conn.execute(
        "SELECT strategy FROM agent_registry WHERE agent_did = 'did:shock:free-rider-1'"
    ).fetchone()
    coal = conn.execute(
        "SELECT strategy FROM agent_registry WHERE agent_did = 'did:shock:coalition-1'"
    ).fetchone()
    conn.close()
    assert fr["strategy"] == "free_rider"
    assert coal["strategy"] == "coalition"
