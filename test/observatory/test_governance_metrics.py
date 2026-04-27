"""Governance experiment metrics endpoint tests.

Covers GET /api/v1/observatory/governance/metrics:
- PCR (Project Completion Rate)
- PSR (Pool Sustainability Rate)
- CAU (Capability-Adjusted Utilization)
- SI  (Specialization Index)
- CDR (Coordination Detection Rate)
- OPA (Override Panel Activation count)
- ECP (Endogenous Compliance Premium)
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from oasis.api import app
from oasis.observatory import endpoints as obs_ep
from oasis.observatory.service import ObservatoryService


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def obs_db(tmp_path: Path) -> Path:
    """Fresh observatory DB wired into the observatory endpoints module."""
    db = tmp_path / "metrics_obs_test.db"
    obs_ep.init_observatory_db(str(db))
    return db


@pytest.fixture()
def metrics_client(obs_db: Path) -> TestClient:
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture()
def seeded_metrics_db(obs_db: Path) -> ObservatoryService:
    """Seed the observatory DB with cross-branch data for metrics computation."""
    conn = sqlite3.connect(str(obs_db))
    conn.execute("PRAGMA foreign_keys = OFF")

    # Ensure cross-branch tables exist (mirrors api.py seed_demo pattern)
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS agent_registry (
            agent_did TEXT PRIMARY KEY, agent_type TEXT NOT NULL,
            capability_tier TEXT DEFAULT 't1',
            display_name TEXT NOT NULL,
            reputation_score REAL NOT NULL DEFAULT 0.5,
            active BOOLEAN DEFAULT 1
        );
        CREATE TABLE IF NOT EXISTS agent_balance (
            agent_did TEXT PRIMARY KEY, total_balance REAL DEFAULT 100.0,
            locked_stake REAL DEFAULT 0.0, available_balance REAL DEFAULT 100.0
        );
        CREATE TABLE IF NOT EXISTS legislative_session (
            session_id TEXT PRIMARY KEY, state TEXT NOT NULL DEFAULT 'SESSION_INIT',
            epoch INTEGER DEFAULT 0, governance_mode TEXT DEFAULT 'full',
            milestone_id TEXT, quality_crisis BOOLEAN DEFAULT 0,
            mission_budget_cap REAL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, failed_reason TEXT
        );
        CREATE TABLE IF NOT EXISTS task_assignment (
            task_id TEXT PRIMARY KEY, session_id TEXT NOT NULL,
            node_id TEXT NOT NULL, agent_did TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS guardian_alert (
            alert_id TEXT PRIMARY KEY, task_id TEXT NOT NULL,
            alert_type TEXT NOT NULL, severity TEXT NOT NULL,
            details TEXT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS treasury (
            entry_id INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id TEXT, agent_did TEXT, entry_type TEXT NOT NULL,
            amount REAL NOT NULL, balance_after REAL NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS reputation_ledger (
            entry_id INTEGER PRIMARY KEY AUTOINCREMENT,
            agent_did TEXT NOT NULL, old_score REAL NOT NULL,
            new_score REAL NOT NULL, performance_score REAL,
            lambda REAL, reason TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    """)

    # 4 sessions: 3 DEPLOYED + 1 SESSION_INIT → PCR = 3/4 = 0.75
    for sid, state in [
        ("sess-d1", "DEPLOYED"),
        ("sess-d2", "DEPLOYED"),
        ("sess-d3", "DEPLOYED"),
        ("sess-i1", "SESSION_INIT"),
    ]:
        conn.execute(
            "INSERT OR IGNORE INTO legislative_session (session_id, state, governance_mode, mission_budget_cap) "
            "VALUES (?, ?, 'full', 1000.0)",
            (sid, state),
        )

    # 3 producers: 2 active (T1, T3), 1 inactive (T1) → PSR = 2/3
    conn.execute(
        "INSERT OR IGNORE INTO agent_registry "
        "(agent_did, agent_type, capability_tier, display_name, reputation_score, active) "
        "VALUES ('did:m:t1-active', 'producer', 't1', 'T1 Active', 0.5, 1)"
    )
    conn.execute(
        "INSERT OR IGNORE INTO agent_registry "
        "(agent_did, agent_type, capability_tier, display_name, reputation_score, active) "
        "VALUES ('did:m:t3-active', 'producer', 't3', 'T3 Active', 0.7, 1)"
    )
    conn.execute(
        "INSERT OR IGNORE INTO agent_registry "
        "(agent_did, agent_type, capability_tier, display_name, reputation_score, active) "
        "VALUES ('did:m:t1-inactive', 'producer', 't1', 'T1 Inactive', 0.4, 0)"
    )

    # 3 tasks: T1 completed (1), T3 completed (2) → CAU = 2/3
    conn.execute(
        "INSERT OR IGNORE INTO task_assignment (task_id, session_id, node_id, agent_did, status) "
        "VALUES ('task-t1-c', 'sess-d1', 'n1', 'did:m:t1-active', 'completed')"
    )
    conn.execute(
        "INSERT OR IGNORE INTO task_assignment (task_id, session_id, node_id, agent_did, status) "
        "VALUES ('task-t3-c1', 'sess-d2', 'n2', 'did:m:t3-active', 'completed')"
    )
    conn.execute(
        "INSERT OR IGNORE INTO task_assignment (task_id, session_id, node_id, agent_did, status) "
        "VALUES ('task-t3-c2', 'sess-d3', 'n3', 'did:m:t3-active', 'settled')"
    )

    # 1 guardian alert → OPA = 1
    conn.execute(
        "INSERT OR IGNORE INTO guardian_alert (alert_id, task_id, alert_type, severity, details) "
        "VALUES ('alert-1', 'task-t1-c', 'timeout', 'high', 'Exceeded timeout')"
    )

    # 2 reputation ledger entries: +0.1 and +0.2 → ECP = 0.15
    conn.execute(
        "INSERT INTO reputation_ledger (agent_did, old_score, new_score, performance_score, reason) "
        "VALUES ('did:m:t1-active', 0.5, 0.6, 0.8, 'task completion')"
    )
    conn.execute(
        "INSERT INTO reputation_ledger (agent_did, old_score, new_score, performance_score, reason) "
        "VALUES ('did:m:t3-active', 0.7, 0.9, 0.95, 'excellent output')"
    )

    conn.commit()
    conn.close()
    return ObservatoryService(str(obs_db))


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_governance_metrics_endpoint_returns_200(metrics_client, seeded_metrics_db):
    """GET /api/v1/observatory/governance/metrics returns 200."""
    resp = metrics_client.get("/api/v1/observatory/governance/metrics")
    assert resp.status_code == 200


def test_governance_metrics_has_required_keys(metrics_client, seeded_metrics_db):
    """Response includes all 7 primary metric keys."""
    resp = metrics_client.get("/api/v1/observatory/governance/metrics")
    data = resp.json()
    for key in ("pcr", "psr", "cau", "si", "cdr", "opa", "ecp"):
        assert key in data, f"Missing metric key: {key}"


def test_pcr_computation(seeded_metrics_db: ObservatoryService):
    """PCR = DEPLOYED sessions / total sessions = 3/4 = 0.75."""
    metrics = seeded_metrics_db.get_governance_metrics()
    assert metrics["session_count"] == 4
    assert metrics["pcr"] == pytest.approx(0.75, abs=0.001)


def test_psr_computation(seeded_metrics_db: ObservatoryService):
    """PSR = active producers / total producers = 2/3."""
    metrics = seeded_metrics_db.get_governance_metrics()
    assert metrics["active_agent_count"] == 2
    assert metrics["psr"] == pytest.approx(2 / 3, abs=0.001)


def test_cau_computation(seeded_metrics_db: ObservatoryService):
    """CAU = T3+T5 completed / all completed = 2/3."""
    metrics = seeded_metrics_db.get_governance_metrics()
    assert metrics["cau"] == pytest.approx(2 / 3, abs=0.001)


def test_opa_count(seeded_metrics_db: ObservatoryService):
    """OPA = guardian alerts raised = 1."""
    metrics = seeded_metrics_db.get_governance_metrics()
    assert metrics["opa"] == 1


def test_ecp_computation(seeded_metrics_db: ObservatoryService):
    """ECP = mean(new_score - old_score) = mean(0.1, 0.2) = 0.15."""
    metrics = seeded_metrics_db.get_governance_metrics()
    assert metrics["ecp"] == pytest.approx(0.15, abs=0.001)


def test_governance_metrics_empty_db_returns_zeros(obs_db: Path):
    """Fresh DB with no data returns zeroed metrics without errors."""
    service = ObservatoryService(str(obs_db))
    metrics = service.get_governance_metrics()
    assert metrics["pcr"] == 0.0
    assert metrics["psr"] == 1.0  # no agents → default 1.0
    assert metrics["cau"] == 0.0
    assert metrics["si"] == 0.0
    assert metrics["cdr"] == 0.0
    assert metrics["opa"] == 0
    assert metrics["ecp"] == 0.0
