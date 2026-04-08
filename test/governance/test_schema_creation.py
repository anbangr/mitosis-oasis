"""P1 — Test governance table creation."""
import sqlite3
from pathlib import Path

import pytest

from oasis.governance.schema import create_governance_tables

EXPECTED_TABLES = sorted([
    "agent_registry",
    "bid",
    "clerk_registry",
    "constitution",
    "contract_spec",
    "dag_edge",
    "dag_node",
    "deliberation_round",
    "legislative_session",
    "message_log",
    "proposal",
    "regulatory_decision",
    "reputation_ledger",
    "straw_poll",
    "vote",
])


def _get_tables(db_path: Path) -> list[str]:
    conn = sqlite3.connect(str(db_path))
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' "
        "AND name != 'sqlite_sequence' ORDER BY name"
    ).fetchall()
    conn.close()
    return [r[0] for r in rows]


def test_all_15_tables_created(db_path: Path):
    """create_governance_tables produces exactly 15 tables."""
    create_governance_tables(db_path)
    tables = _get_tables(db_path)
    assert tables == EXPECTED_TABLES
    assert len(tables) == 15


def test_idempotent_recreation(db_path: Path):
    """Calling create_governance_tables twice does not error or duplicate."""
    create_governance_tables(db_path)
    create_governance_tables(db_path)  # second call — should be no-op
    tables = _get_tables(db_path)
    assert len(tables) == 15


def test_foreign_key_enforcement(db_path: Path):
    """FK constraints are enforced (proposal references non-existent session)."""
    create_governance_tables(db_path)
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA foreign_keys = ON")
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO proposal "
            "(proposal_id, session_id, proposer_did, dag_spec, "
            "token_budget_total, deadline_ms) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            ("p-1", "nonexistent-session", "did:x", "{}", 100.0, 60000),
        )
    conn.close()
