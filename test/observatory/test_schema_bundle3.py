"""Bundle 3 schema additions — on_chain_anchor and event_log.anchor_id.

Test Spec
---------
T1  on_chain_anchor table created
T2  event_log.anchor_id column present
T3  Idempotent rerun
E1  Foreign-key reference validity
E2  Constitution params seeded with correct default values
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from oasis.observatory.schema import create_observatory_tables
from oasis.governance.schema import create_governance_tables, seed_constitution


# ---------------------------------------------------------------------------
# T1 — on_chain_anchor table created
# ---------------------------------------------------------------------------

def test_on_chain_anchor_table_present(tmp_path: Path) -> None:
    """Fresh observatory database contains on_chain_anchor table."""
    db = tmp_path / "obs.db"
    create_observatory_tables(db)
    conn = sqlite3.connect(str(db))
    try:
        tables = {
            r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        assert "on_chain_anchor" in tables
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# T2 — event_log.anchor_id column
# ---------------------------------------------------------------------------

def test_event_log_has_anchor_id_column(tmp_path: Path) -> None:
    """event_log schema contains anchor_id column after creation."""
    db = tmp_path / "obs.db"
    create_observatory_tables(db)
    conn = sqlite3.connect(str(db))
    try:
        cols = {r[1] for r in conn.execute("PRAGMA table_info(event_log)")}
        assert "anchor_id" in cols
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# T3 — Idempotent rerun
# ---------------------------------------------------------------------------

def test_idempotent_rerun(tmp_path: Path) -> None:
    """Calling create_observatory_tables twice on the same DB raises no error."""
    db = tmp_path / "obs.db"
    create_observatory_tables(db)
    # Second call must not raise
    create_observatory_tables(db)
    conn = sqlite3.connect(str(db))
    try:
        tables = {
            r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        assert "on_chain_anchor" in tables
        cols = {r[1] for r in conn.execute("PRAGMA table_info(event_log)")}
        assert "anchor_id" in cols
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# E1 — Foreign-key reference validity
# ---------------------------------------------------------------------------

def test_anchor_id_foreign_key_valid(tmp_path: Path) -> None:
    """event_log.anchor_id references on_chain_anchor(anchor_id) correctly."""
    db = tmp_path / "obs.db"
    create_observatory_tables(db)
    conn = sqlite3.connect(str(db))
    try:
        conn.execute("PRAGMA foreign_keys = ON")
        # Insert a valid anchor
        conn.execute(
            "INSERT INTO on_chain_anchor "
            "(anchor_id, merkle_root_hex, batch_start_seq, batch_end_seq, event_count, mission_id) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            ("anchor-001", "aabbccdd", 1, 10, 10, "mission-001"),
        )
        # Insert an event_log row referencing that anchor
        conn.execute(
            "INSERT INTO event_log "
            "(event_id, event_type, timestamp, session_id, agent_did, payload, sequence_number, anchor_id) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            ("evt-001", "TEST", 0.0, "sess-001", "did:test:1", "{}", 1, "anchor-001"),
        )
        conn.commit()
        # Verify the row exists
        row = conn.execute(
            "SELECT anchor_id FROM event_log WHERE event_id = ?", ("evt-001",)
        ).fetchone()
        assert row is not None
        assert row[0] == "anchor-001"
    finally:
        conn.close()


def test_anchor_id_foreign_key_invalid_rejected(tmp_path: Path) -> None:
    """Inserting an event_log row with a non-existent anchor_id is rejected."""
    db = tmp_path / "obs.db"
    create_observatory_tables(db)
    conn = sqlite3.connect(str(db))
    try:
        conn.execute("PRAGMA foreign_keys = ON")
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO event_log "
                "(event_id, event_type, timestamp, session_id, agent_did, payload, sequence_number, anchor_id) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                ("evt-002", "TEST", 0.0, "sess-001", "did:test:1", "{}", 1, "nonexistent"),
            )
            conn.commit()
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# E2 — Constitution params seeded with correct default values
# ---------------------------------------------------------------------------

_BUNDLE3_CONSTITUTION_PARAMS = [
    ("tau_anchor_small_seconds", 10.0, "integer"),
    ("tau_anchor_large_seconds", 60.0, "integer"),
    ("anchor_batch_max_size", 1000.0, "integer"),
    ("anchor_large_dag_threshold", 100.0, "integer"),
]


@pytest.fixture()
def gov_db(tmp_path: Path) -> Path:
    """Fresh governance DB with tables and seeded constitution."""
    db = tmp_path / "gov.db"
    create_governance_tables(db)
    seed_constitution(db)
    return db


@pytest.mark.parametrize("param_name,expected_value,expected_type", _BUNDLE3_CONSTITUTION_PARAMS)
def test_bundle3_constitution_params_present(
    gov_db: Path, param_name: str, expected_value: float, expected_type: str
) -> None:
    """Each Bundle 3 constitutional parameter is present with the correct default."""
    conn = sqlite3.connect(str(gov_db))
    try:
        row = conn.execute(
            "SELECT param_value, param_type FROM constitution WHERE param_name = ?",
            (param_name,),
        ).fetchone()
        assert row is not None, f"Missing constitution param: {param_name}"
        assert row[0] == expected_value
        assert row[1] == expected_type
    finally:
        conn.close()


def test_bundle3_constitution_params_idempotent(gov_db: Path) -> None:
    """Re-seeding constitution does not overwrite existing Bundle 3 params."""
    # Re-seed
    seed_constitution(gov_db)
    conn = sqlite3.connect(str(gov_db))
    try:
        for param_name, expected_value, expected_type in _BUNDLE3_CONSTITUTION_PARAMS:
            row = conn.execute(
                "SELECT param_value, param_type FROM constitution WHERE param_name = ?",
                (param_name,),
            ).fetchone()
            assert row is not None, f"Missing constitution param after re-seed: {param_name}"
            assert row[0] == expected_value
            assert row[1] == expected_type
    finally:
        conn.close()
