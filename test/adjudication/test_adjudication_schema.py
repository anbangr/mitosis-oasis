"""Tests for adjudication schema creation."""
from __future__ import annotations

import sqlite3
from pathlib import Path

from oasis.governance.schema import create_governance_tables, seed_clerks, seed_constitution
from oasis.execution.schema import create_execution_tables
from oasis.adjudication.schema import create_adjudication_tables


def test_tables_created(adjudication_db: Path) -> None:
    """All 3 adjudication tables exist after creation."""
    conn = sqlite3.connect(str(adjudication_db))
    tables = {
        r[0]
        for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }
    conn.close()
    assert "coordination_flag" in tables
    assert "adjudication_decision" in tables
    assert "treasury" in tables


def test_idempotent(adjudication_db: Path) -> None:
    """Calling create_adjudication_tables twice does not raise."""
    create_adjudication_tables(adjudication_db)
    # Verify tables still exist
    conn = sqlite3.connect(str(adjudication_db))
    tables = {
        r[0]
        for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }
    conn.close()
    assert "coordination_flag" in tables
    assert "adjudication_decision" in tables
    assert "treasury" in tables


def test_fk_constraints(adjudication_db: Path) -> None:
    """FK constraints enforced on adjudication_decision."""
    conn = sqlite3.connect(str(adjudication_db))
    conn.execute("PRAGMA foreign_keys = ON")

    # Insert an agent first
    conn.execute(
        "INSERT INTO agent_registry "
        "(agent_did, agent_type, display_name, human_principal) "
        "VALUES ('did:test:fk', 'producer', 'FK Test', 'human@test.com')"
    )

    # Insert a valid adjudication_decision should work
    conn.execute(
        "INSERT INTO adjudication_decision "
        "(decision_id, agent_did, decision_type, severity, reason, layer1_result) "
        "VALUES ('dec-fk-test', 'did:test:fk', 'freeze', 'CRITICAL', 'test', 'frozen')"
    )
    conn.commit()

    # FK violation: non-existent agent_did should fail
    import pytest
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO adjudication_decision "
            "(decision_id, agent_did, decision_type, severity, reason, layer1_result) "
            "VALUES ('dec-fk-bad', 'did:nonexistent', 'freeze', 'CRITICAL', 'test', 'frozen')"
        )
    conn.close()
