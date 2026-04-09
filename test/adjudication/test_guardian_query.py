"""Tests for Guardian alert querying with filters."""
from __future__ import annotations

import sqlite3
from pathlib import Path

from oasis.adjudication.guardian import Guardian
from oasis.config import PlatformConfig


def _seed_alerts(db_path: Path) -> None:
    """Seed multiple guardian alerts for query testing."""
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA foreign_keys = ON")

    # Two agents
    for did in ("did:query:a1", "did:query:a2"):
        conn.execute(
            "INSERT OR IGNORE INTO agent_registry "
            "(agent_did, agent_type, display_name, human_principal) "
            "VALUES (?, 'producer', 'Query Agent', 'h@t.com')",
            (did,),
        )

    # Session
    conn.execute(
        "INSERT OR IGNORE INTO legislative_session "
        "(session_id, state, epoch) VALUES ('qs-001', 'DEPLOYED', 0)"
    )

    # Tasks — one per agent
    conn.execute(
        "INSERT OR IGNORE INTO task_assignment "
        "(task_id, session_id, node_id, agent_did, status) "
        "VALUES ('qtask-a1', 'qs-001', 'qn1', 'did:query:a1', 'committed')"
    )
    conn.execute(
        "INSERT OR IGNORE INTO task_assignment "
        "(task_id, session_id, node_id, agent_did, status) "
        "VALUES ('qtask-a2', 'qs-001', 'qn2', 'did:query:a2', 'committed')"
    )

    # Alerts
    conn.execute(
        "INSERT INTO guardian_alert "
        "(alert_id, task_id, alert_type, severity, details) "
        "VALUES ('qa-1', 'qtask-a1', 'schema_failure', 'CRITICAL', 'bad schema')"
    )
    conn.execute(
        "INSERT INTO guardian_alert "
        "(alert_id, task_id, alert_type, severity, details) "
        "VALUES ('qa-2', 'qtask-a1', 'timeout', 'WARNING', 'slow')"
    )
    conn.execute(
        "INSERT INTO guardian_alert "
        "(alert_id, task_id, alert_type, severity, details) "
        "VALUES ('qa-3', 'qtask-a2', 'schema_failure', 'CRITICAL', 'bad schema 2')"
    )
    conn.commit()
    conn.close()


def test_filter_by_severity(adjudication_db: Path, config: PlatformConfig) -> None:
    """Filter alerts by severity returns only matching."""
    _seed_alerts(adjudication_db)
    guardian = Guardian(config, adjudication_db)

    critical = guardian.get_alerts(severity="CRITICAL")
    assert len(critical) == 2
    assert all(a.severity == "CRITICAL" for a in critical)

    warning = guardian.get_alerts(severity="WARNING")
    assert len(warning) == 1
    assert warning[0].severity == "WARNING"


def test_filter_by_agent(adjudication_db: Path, config: PlatformConfig) -> None:
    """Filter alerts by agent_did returns only that agent's alerts."""
    _seed_alerts(adjudication_db)
    guardian = Guardian(config, adjudication_db)

    a1_alerts = guardian.get_alerts(agent_did="did:query:a1")
    assert len(a1_alerts) == 2

    a2_alerts = guardian.get_alerts(agent_did="did:query:a2")
    assert len(a2_alerts) == 1


def test_filter_by_task(adjudication_db: Path, config: PlatformConfig) -> None:
    """Filter alerts by task_id returns only that task's alerts."""
    _seed_alerts(adjudication_db)
    guardian = Guardian(config, adjudication_db)

    alerts = guardian.get_alerts(task_id="qtask-a1")
    assert len(alerts) == 2

    alerts = guardian.get_alerts(task_id="qtask-a2")
    assert len(alerts) == 1
