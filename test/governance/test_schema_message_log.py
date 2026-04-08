"""P1 — Test message_log table operations."""
import json
import sqlite3
import time
from pathlib import Path

import pytest

from oasis.governance.schema import create_governance_tables


def _connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA foreign_keys = ON")
    conn.row_factory = sqlite3.Row
    return conn


def _setup_session(conn: sqlite3.Connection, session_id: str = "sess-1") -> None:
    """Insert a session so FK constraint is satisfied."""
    conn.execute(
        "INSERT OR IGNORE INTO legislative_session (session_id, mission_budget_cap) "
        "VALUES (?, ?)",
        (session_id, 10000.0),
    )
    conn.commit()


def test_message_logged(db_path: Path):
    """A protocol message can be inserted and retrieved."""
    create_governance_tables(db_path)
    conn = _connect(db_path)
    _setup_session(conn)
    payload = json.dumps({"action": "attest"})
    conn.execute(
        "INSERT INTO message_log (session_id, msg_type, sender_did, receiver, payload) "
        "VALUES (?, ?, ?, ?, ?)",
        ("sess-1", "IdentityVerificationRequest", "did:mock:p-1", "did:oasis:clerk-registrar", payload),
    )
    conn.commit()
    row = conn.execute("SELECT * FROM message_log WHERE session_id = 'sess-1'").fetchone()
    conn.close()
    assert row["msg_type"] == "IdentityVerificationRequest"
    assert row["sender_did"] == "did:mock:p-1"
    assert json.loads(row["payload"])["action"] == "attest"


def test_chronological_ordering(db_path: Path):
    """Messages are ordered by log_id (autoincrement)."""
    create_governance_tables(db_path)
    conn = _connect(db_path)
    _setup_session(conn)
    types = ["IdentityVerificationRequest", "IdentityVerificationResponse", "ProposalSubmission"]
    for mt in types:
        conn.execute(
            "INSERT INTO message_log (session_id, msg_type, sender_did) "
            "VALUES (?, ?, ?)",
            ("sess-1", mt, "did:mock:p-1"),
        )
    conn.commit()
    rows = conn.execute(
        "SELECT msg_type FROM message_log WHERE session_id = 'sess-1' ORDER BY log_id"
    ).fetchall()
    conn.close()
    assert [r["msg_type"] for r in rows] == types


def test_msg_type_not_null(db_path: Path):
    """msg_type column is NOT NULL."""
    create_governance_tables(db_path)
    conn = _connect(db_path)
    _setup_session(conn)
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO message_log (session_id, msg_type, sender_did) "
            "VALUES (?, ?, ?)",
            ("sess-1", None, "did:mock:p-1"),
        )
    conn.close()
