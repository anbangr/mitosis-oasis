"""Tests for execution schema — table creation, idempotency, FK constraints."""
from __future__ import annotations

import sqlite3
from pathlib import Path

from oasis.governance.schema import create_governance_tables, seed_clerks, seed_constitution
from oasis.execution.schema import create_execution_tables


EXPECTED_TABLES = [
    "task_assignment",
    "task_commitment",
    "task_output",
    "output_validation",
    "settlement",
    "agent_balance",
]


def test_tables_created(execution_db: Path) -> None:
    """All 6 execution tables exist after create_execution_tables."""
    conn = sqlite3.connect(str(execution_db))
    tables = [
        r[0]
        for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    ]
    conn.close()
    for t in EXPECTED_TABLES:
        assert t in tables, f"Table {t} not found"


def test_idempotent(execution_db: Path) -> None:
    """Calling create_execution_tables twice does not raise."""
    create_execution_tables(execution_db)
    # Verify tables still intact
    conn = sqlite3.connect(str(execution_db))
    count = conn.execute(
        "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name IN "
        "('task_assignment','task_commitment','task_output',"
        "'output_validation','settlement','agent_balance')"
    ).fetchone()[0]
    conn.close()
    assert count == 6


def test_fk_constraints(execution_db: Path) -> None:
    """Foreign key constraints prevent orphan rows in execution tables."""
    conn = sqlite3.connect(str(execution_db))
    conn.execute("PRAGMA foreign_keys = ON")

    # Try inserting a task_assignment with a non-existent session
    try:
        conn.execute(
            "INSERT INTO task_assignment (task_id, session_id, node_id, agent_did) "
            "VALUES ('t1', 'no-such-session', 'n1', 'no-such-agent')"
        )
        conn.commit()
        fk_violated = False
    except sqlite3.IntegrityError:
        fk_violated = True
    finally:
        conn.close()

    assert fk_violated, "FK constraint should prevent orphan task_assignment"
