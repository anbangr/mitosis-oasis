"""P1 — Test agent_registry table operations."""
import sqlite3
from pathlib import Path

import pytest

from oasis.governance.schema import create_governance_tables


def _connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA foreign_keys = ON")
    conn.row_factory = sqlite3.Row
    return conn


def test_register_producer(db_path: Path):
    """Insert a producer agent."""
    create_governance_tables(db_path)
    conn = _connect(db_path)
    conn.execute(
        "INSERT INTO agent_registry (agent_did, agent_type, display_name) "
        "VALUES (?, ?, ?)",
        ("did:mock:p-1", "producer", "Producer 1"),
    )
    conn.commit()
    row = conn.execute(
        "SELECT * FROM agent_registry WHERE agent_did = 'did:mock:p-1'"
    ).fetchone()
    conn.close()
    assert row["agent_type"] == "producer"
    assert row["display_name"] == "Producer 1"


def test_register_clerk(db_path: Path):
    """Insert a clerk agent."""
    create_governance_tables(db_path)
    conn = _connect(db_path)
    conn.execute(
        "INSERT INTO agent_registry (agent_did, agent_type, display_name) "
        "VALUES (?, ?, ?)",
        ("did:mock:c-1", "clerk", "Clerk 1"),
    )
    conn.commit()
    row = conn.execute(
        "SELECT * FROM agent_registry WHERE agent_did = 'did:mock:c-1'"
    ).fetchone()
    conn.close()
    assert row["agent_type"] == "clerk"


def test_duplicate_did_rejected(db_path: Path):
    """Inserting the same agent_did twice raises IntegrityError."""
    create_governance_tables(db_path)
    conn = _connect(db_path)
    conn.execute(
        "INSERT INTO agent_registry (agent_did, agent_type, display_name) "
        "VALUES (?, ?, ?)",
        ("did:mock:dup", "producer", "First"),
    )
    conn.commit()
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO agent_registry (agent_did, agent_type, display_name) "
            "VALUES (?, ?, ?)",
            ("did:mock:dup", "producer", "Duplicate"),
        )
    conn.close()


def test_type_constraint_enforced(db_path: Path):
    """agent_type must be 'producer' or 'clerk'."""
    create_governance_tables(db_path)
    conn = _connect(db_path)
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO agent_registry (agent_did, agent_type, display_name) "
            "VALUES (?, ?, ?)",
            ("did:mock:bad", "admin", "Bad Type"),
        )
    conn.close()


def test_reputation_default(db_path: Path):
    """Default reputation_score is 0.5."""
    create_governance_tables(db_path)
    conn = _connect(db_path)
    conn.execute(
        "INSERT INTO agent_registry (agent_did, agent_type, display_name) "
        "VALUES (?, ?, ?)",
        ("did:mock:rep", "producer", "Rep Test"),
    )
    conn.commit()
    row = conn.execute(
        "SELECT reputation_score FROM agent_registry WHERE agent_did = 'did:mock:rep'"
    ).fetchone()
    conn.close()
    assert row["reputation_score"] == pytest.approx(0.5)


def test_deactivation_works(db_path: Path):
    """Setting active = 0 deactivates an agent."""
    create_governance_tables(db_path)
    conn = _connect(db_path)
    conn.execute(
        "INSERT INTO agent_registry (agent_did, agent_type, display_name) "
        "VALUES (?, ?, ?)",
        ("did:mock:deact", "producer", "Deactivate Me"),
    )
    conn.commit()
    conn.execute(
        "UPDATE agent_registry SET active = 0 WHERE agent_did = 'did:mock:deact'"
    )
    conn.commit()
    row = conn.execute(
        "SELECT active FROM agent_registry WHERE agent_did = 'did:mock:deact'"
    ).fetchone()
    conn.close()
    assert row["active"] == 0
