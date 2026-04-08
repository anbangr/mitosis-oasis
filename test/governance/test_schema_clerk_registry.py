"""P1 — Test clerk_registry table operations."""
import json
import sqlite3
from pathlib import Path

import pytest

from oasis.governance.schema import create_governance_tables, seed_clerks


def _connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA foreign_keys = ON")
    conn.row_factory = sqlite3.Row
    return conn


def test_all_4_clerks_registered(db_path: Path):
    """seed_clerks inserts all 4 clerks into both registries."""
    create_governance_tables(db_path)
    seed_clerks(db_path)
    conn = _connect(db_path)
    agent_rows = conn.execute(
        "SELECT * FROM agent_registry WHERE agent_type = 'clerk'"
    ).fetchall()
    clerk_rows = conn.execute("SELECT * FROM clerk_registry").fetchall()
    conn.close()
    assert len(agent_rows) == 4
    assert len(clerk_rows) == 4
    roles = {r["clerk_role"] for r in clerk_rows}
    assert roles == {"registrar", "speaker", "regulator", "codifier"}


def test_role_constraint_enforced(db_path: Path):
    """clerk_role must be one of the 4 valid roles."""
    create_governance_tables(db_path)
    conn = _connect(db_path)
    # First insert into agent_registry
    conn.execute(
        "INSERT INTO agent_registry (agent_did, agent_type, display_name) "
        "VALUES (?, ?, ?)",
        ("did:mock:bad-clerk", "clerk", "Bad Clerk"),
    )
    conn.commit()
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO clerk_registry (agent_did, clerk_role, authority_envelope) "
            "VALUES (?, ?, ?)",
            ("did:mock:bad-clerk", "judge", "{}"),
        )
    conn.close()


def test_authority_envelope_stored(db_path: Path):
    """Authority envelope JSON is stored and retrievable."""
    create_governance_tables(db_path)
    seed_clerks(db_path)
    conn = _connect(db_path)
    row = conn.execute(
        "SELECT authority_envelope FROM clerk_registry "
        "WHERE clerk_role = 'registrar'"
    ).fetchone()
    conn.close()
    envelope = json.loads(row["authority_envelope"])
    assert envelope["role"] == "registrar"
    assert "registrar:*" in envelope["permissions"]


def test_non_clerk_agent_rejected_from_clerk_registry(db_path: Path):
    """FK constraint: clerk_registry.agent_did must exist in agent_registry."""
    create_governance_tables(db_path)
    conn = _connect(db_path)
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO clerk_registry (agent_did, clerk_role, authority_envelope) "
            "VALUES (?, ?, ?)",
            ("did:mock:nonexistent", "speaker", "{}"),
        )
    conn.close()
