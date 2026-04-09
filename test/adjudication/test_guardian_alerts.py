"""Tests for Guardian alert creation based on validation results."""
from __future__ import annotations

from pathlib import Path

from oasis.adjudication.guardian import Guardian, GuardianAlert
from oasis.config import PlatformConfig


def test_schema_failure_critical(adjudication_db: Path, config: PlatformConfig) -> None:
    """Schema failure produces a CRITICAL alert."""
    guardian = Guardian(config, adjudication_db)
    # We need a task_id that exists — but guardian_alert FK is on task_assignment
    # Disable FK for this direct alert test by using a raw task_id
    # Actually guardian_alert has FK to task_assignment, so we need to seed one
    import sqlite3
    conn = sqlite3.connect(str(adjudication_db))
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute(
        "INSERT INTO agent_registry "
        "(agent_did, agent_type, display_name, human_principal) "
        "VALUES ('did:guardian:test', 'producer', 'Guard Test', 'h@t.com')"
    )
    conn.execute(
        "INSERT INTO legislative_session "
        "(session_id, state, epoch) VALUES ('gs-001', 'DEPLOYED', 0)"
    )
    conn.execute(
        "INSERT INTO task_assignment "
        "(task_id, session_id, node_id, agent_did, status) "
        "VALUES ('gtask-001', 'gs-001', 'gnode', 'did:guardian:test', 'committed')"
    )
    conn.commit()
    conn.close()

    result = {
        "task_id": "gtask-001",
        "schema_valid": False,
        "timeout_valid": True,
        "quality_score": 0.9,
    }
    alert = guardian.process_validation(result)
    assert alert is not None
    assert alert.severity == "CRITICAL"
    assert alert.alert_type == "schema_failure"


def test_timeout_warning(adjudication_db: Path, config: PlatformConfig) -> None:
    """Timeout failure produces a WARNING alert."""
    guardian = Guardian(config, adjudication_db)
    import sqlite3
    conn = sqlite3.connect(str(adjudication_db))
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute(
        "INSERT INTO agent_registry "
        "(agent_did, agent_type, display_name, human_principal) "
        "VALUES ('did:guardian:t2', 'producer', 'Guard T2', 'h@t.com')"
    )
    conn.execute(
        "INSERT INTO legislative_session "
        "(session_id, state, epoch) VALUES ('gs-002', 'DEPLOYED', 0)"
    )
    conn.execute(
        "INSERT INTO task_assignment "
        "(task_id, session_id, node_id, agent_did, status) "
        "VALUES ('gtask-002', 'gs-002', 'gnode2', 'did:guardian:t2', 'committed')"
    )
    conn.commit()
    conn.close()

    result = {
        "task_id": "gtask-002",
        "schema_valid": True,
        "timeout_valid": False,
        "quality_score": 0.9,
    }
    alert = guardian.process_validation(result)
    assert alert is not None
    assert alert.severity == "WARNING"
    assert alert.alert_type == "timeout"


def test_quality_below_threshold_warning(adjudication_db: Path, config: PlatformConfig) -> None:
    """Quality below threshold produces a WARNING alert."""
    guardian = Guardian(config, adjudication_db)
    import sqlite3
    conn = sqlite3.connect(str(adjudication_db))
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute(
        "INSERT INTO agent_registry "
        "(agent_did, agent_type, display_name, human_principal) "
        "VALUES ('did:guardian:t3', 'producer', 'Guard T3', 'h@t.com')"
    )
    conn.execute(
        "INSERT INTO legislative_session "
        "(session_id, state, epoch) VALUES ('gs-003', 'DEPLOYED', 0)"
    )
    conn.execute(
        "INSERT INTO task_assignment "
        "(task_id, session_id, node_id, agent_did, status) "
        "VALUES ('gtask-003', 'gs-003', 'gnode3', 'did:guardian:t3', 'committed')"
    )
    conn.commit()
    conn.close()

    result = {
        "task_id": "gtask-003",
        "schema_valid": True,
        "timeout_valid": True,
        "quality_score": 0.2,
    }
    alert = guardian.process_validation(result)
    assert alert is not None
    assert alert.severity == "WARNING"
    assert alert.alert_type == "quality_below_threshold"


def test_anomaly_critical(adjudication_db: Path, config: PlatformConfig) -> None:
    """check_anomaly is a v1 no-op, returns None."""
    guardian = Guardian(config, adjudication_db)
    alert = guardian.check_anomaly("some-task", {"output": "data"})
    assert alert is None


def test_valid_output_no_alert(adjudication_db: Path, config: PlatformConfig) -> None:
    """Valid output does not produce an alert."""
    guardian = Guardian(config, adjudication_db)
    result = {
        "task_id": "any-task",
        "schema_valid": True,
        "timeout_valid": True,
        "quality_score": 0.9,
    }
    alert = guardian.process_validation(result)
    assert alert is None
