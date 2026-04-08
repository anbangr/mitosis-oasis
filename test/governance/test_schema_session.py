"""P1 — Test legislative_session table operations."""
import sqlite3
from pathlib import Path

import pytest

from oasis.governance.schema import create_governance_tables


def _connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA foreign_keys = ON")
    conn.row_factory = sqlite3.Row
    return conn


def test_session_created_with_initial_state(db_path: Path):
    """New session defaults to SESSION_INIT state."""
    create_governance_tables(db_path)
    conn = _connect(db_path)
    conn.execute(
        "INSERT INTO legislative_session (session_id, mission_budget_cap) "
        "VALUES (?, ?)",
        ("sess-1", 10000.0),
    )
    conn.commit()
    row = conn.execute(
        "SELECT state, epoch FROM legislative_session WHERE session_id = 'sess-1'"
    ).fetchone()
    conn.close()
    assert row["state"] == "SESSION_INIT"
    assert row["epoch"] == 0


def test_parent_fk_for_recursive_sessions(db_path: Path):
    """Child session can reference a parent session."""
    create_governance_tables(db_path)
    conn = _connect(db_path)
    conn.execute(
        "INSERT INTO legislative_session (session_id, mission_budget_cap) "
        "VALUES (?, ?)",
        ("parent-1", 50000.0),
    )
    conn.execute(
        "INSERT INTO legislative_session "
        "(session_id, parent_session_id, parent_node_id, mission_budget_cap) "
        "VALUES (?, ?, ?, ?)",
        ("child-1", "parent-1", "node-a", 20000.0),
    )
    conn.commit()
    row = conn.execute(
        "SELECT parent_session_id, parent_node_id FROM legislative_session "
        "WHERE session_id = 'child-1'"
    ).fetchone()
    conn.close()
    assert row["parent_session_id"] == "parent-1"
    assert row["parent_node_id"] == "node-a"


def test_state_update_works(db_path: Path):
    """Session state can be updated."""
    create_governance_tables(db_path)
    conn = _connect(db_path)
    conn.execute(
        "INSERT INTO legislative_session (session_id, mission_budget_cap) "
        "VALUES (?, ?)",
        ("sess-upd", 5000.0),
    )
    conn.commit()
    conn.execute(
        "UPDATE legislative_session SET state = ?, epoch = epoch + 1 "
        "WHERE session_id = ?",
        ("IDENTITY_VERIFICATION", "sess-upd"),
    )
    conn.commit()
    row = conn.execute(
        "SELECT state, epoch FROM legislative_session WHERE session_id = 'sess-upd'"
    ).fetchone()
    conn.close()
    assert row["state"] == "IDENTITY_VERIFICATION"
    assert row["epoch"] == 1


def test_failed_reason_stored(db_path: Path):
    """failed_reason can be set on a FAILED session."""
    create_governance_tables(db_path)
    conn = _connect(db_path)
    conn.execute(
        "INSERT INTO legislative_session (session_id, state, failed_reason, mission_budget_cap) "
        "VALUES (?, ?, ?, ?)",
        ("sess-fail", "FAILED", "Quorum not reached", 1000.0),
    )
    conn.commit()
    row = conn.execute(
        "SELECT state, failed_reason FROM legislative_session "
        "WHERE session_id = 'sess-fail'"
    ).fetchone()
    conn.close()
    assert row["state"] == "FAILED"
    assert row["failed_reason"] == "Quorum not reached"
