"""Bundle 2 schema migration tests — adjudicator_registry, impeachment, watchdog_anomaly.

These tests verify Feature 1 (schema migration) of the Bundle 2 plan.
They MUST be red before the implementation code is written (TDD invariant).
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from oasis.adjudication.schema import create_adjudication_tables
from oasis.governance.schema import create_governance_tables, seed_constitution


# ---------------------------------------------------------------------------
# T1 — New adjudication tables present
# ---------------------------------------------------------------------------


def test_new_adjudication_tables_present(tmp_path: Path) -> None:
    """T1: Fresh DB from create_adjudication_tables contains the three new tables."""
    db_path = tmp_path / "adj.db"
    create_adjudication_tables(db_path)

    conn = sqlite3.connect(str(db_path))
    tables = {
        r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }
    conn.close()

    assert "adjudicator_registry" in tables
    assert "impeachment" in tables
    assert "watchdog_anomaly" in tables


# ---------------------------------------------------------------------------
# T2 — New constitutional parameters seeded with spec defaults
# ---------------------------------------------------------------------------


def test_new_constitutional_parameters_seeded(tmp_path: Path) -> None:
    """T2: seed_constitution inserts the seven new Bundle-2 parameters with correct defaults."""
    db_path = tmp_path / "gov.db"
    create_governance_tables(db_path)
    seed_constitution(db_path)

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    rows = {
        r["param_name"]: r["param_value"]
        for r in conn.execute(
            "SELECT param_name, param_value FROM constitution"
        ).fetchall()
    }
    conn.close()

    assert rows["adjudicator_quorum"] == 7.0
    assert rows["adjudicator_stake"] == 5000.0
    assert rows["watchdog_zscore_threshold"] == 2.0
    assert rows["watchdog_window_days"] == 30.0
    assert rows["watchdog_anomaly_threshold"] == 2.0
    assert rows["max_freeze_duration_ms"] == 259_200_000.0
    assert rows["rotation_max_consecutive"] == 2.0


# ---------------------------------------------------------------------------
# T3 — agent_registry.banned column exists
# ---------------------------------------------------------------------------


def test_agent_registry_banned_column(tmp_path: Path) -> None:
    """T3: agent_registry has a banned BOOLEAN column with default 0."""
    db_path = tmp_path / "gov.db"
    create_governance_tables(db_path)

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    cols = {
        r["name"]: r
        for r in conn.execute("PRAGMA table_info(agent_registry)").fetchall()
    }
    conn.close()

    assert "banned" in cols
    # SQLite stores BOOLEAN as INTEGER; either is acceptable
    assert cols["banned"]["type"] in ("BOOLEAN", "INTEGER")
    assert cols["banned"]["dflt_value"] in ("0", 0, "FALSE")
    assert cols["banned"]["notnull"] == 1


# ---------------------------------------------------------------------------
# T4 — adjudication_decision has frozen_at / manual_extension / issued_by_did
# ---------------------------------------------------------------------------


def test_adjudication_decision_new_columns(tmp_path: Path) -> None:
    """T4: adjudication_decision has frozen_at, manual_extension, and issued_by_did."""
    db_path = tmp_path / "adj.db"
    create_adjudication_tables(db_path)

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    cols = {
        r["name"]: r
        for r in conn.execute("PRAGMA table_info(adjudication_decision)").fetchall()
    }
    conn.close()

    assert "frozen_at" in cols
    assert "manual_extension" in cols
    assert "issued_by_did" in cols

    # manual_extension should be BOOLEAN/INTEGER NOT NULL DEFAULT 0
    assert cols["manual_extension"]["type"] in ("BOOLEAN", "INTEGER")
    assert cols["manual_extension"]["notnull"] == 1
    assert cols["manual_extension"]["dflt_value"] in ("0", 0, "FALSE")

    # issued_by_did should be TEXT (nullable is acceptable)
    assert cols["issued_by_did"]["type"] == "TEXT"

    # frozen_at should be TIMESTAMP (nullable is acceptable)
    assert cols["frozen_at"]["type"] == "TIMESTAMP"


# ---------------------------------------------------------------------------
# Edge case — idempotent re-runs
# ---------------------------------------------------------------------------


def test_create_adjudication_tables_idempotent(tmp_path: Path) -> None:
    """Running create_adjudication_tables twice on the same DB must not raise."""
    db_path = tmp_path / "adj.db"
    create_adjudication_tables(db_path)
    # Second call should succeed silently (idempotent ALTERs)
    create_adjudication_tables(db_path)

    conn = sqlite3.connect(str(db_path))
    tables = {
        r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }
    conn.close()

    assert "adjudicator_registry" in tables
    assert "impeachment" in tables
    assert "watchdog_anomaly" in tables


def test_create_governance_tables_idempotent(tmp_path: Path) -> None:
    """Running create_governance_tables twice on the same DB must not raise."""
    db_path = tmp_path / "gov.db"
    create_governance_tables(db_path)
    create_governance_tables(db_path)  # should not raise

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    cols = {
        r["name"] for r in conn.execute("PRAGMA table_info(agent_registry)").fetchall()
    }
    conn.close()

    assert "banned" in cols


def test_seed_constitution_no_duplicates(tmp_path: Path) -> None:
    """Re-running seed_constitution must not insert duplicate rows."""
    db_path = tmp_path / "gov.db"
    create_governance_tables(db_path)
    seed_constitution(db_path)
    seed_constitution(db_path)  # second run

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT param_name FROM constitution WHERE param_name = ?",
        ("adjudicator_quorum",),
    ).fetchall()
    conn.close()

    assert len(rows) == 1


# ---------------------------------------------------------------------------
# Edge case — migration from pre-Bundle-1 DB
# ---------------------------------------------------------------------------


def test_pre_bundle1_db_migrates_forward(tmp_path: Path) -> None:
    """A DB created without banned or issued_by_did successfully migrates forward."""
    db_path = tmp_path / "legacy.db"
    conn = sqlite3.connect(str(db_path))
    conn.executescript(
        """
        CREATE TABLE agent_registry (
            agent_did         TEXT PRIMARY KEY,
            agent_type        TEXT NOT NULL,
            capability_tier   TEXT NOT NULL DEFAULT 't1',
            display_name      TEXT NOT NULL,
            human_principal   TEXT,
            reputation_score  REAL NOT NULL DEFAULT 0.5,
            strategy          TEXT,
            registered_at     TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            active            BOOLEAN NOT NULL DEFAULT 1
        );
        CREATE TABLE adjudication_decision (
            decision_id     TEXT PRIMARY KEY,
            alert_id        TEXT,
            flag_id         TEXT,
            agent_did       TEXT NOT NULL,
            decision_type   TEXT NOT NULL,
            severity        TEXT NOT NULL,
            reason          TEXT,
            layer1_result   TEXT,
            layer2_advisory TEXT,
            created_at      TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE treasury (
            entry_id      INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id       TEXT,
            agent_did     TEXT,
            entry_type    TEXT NOT NULL,
            amount        REAL NOT NULL,
            balance_after REAL NOT NULL,
            created_at    TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        """
    )
    conn.close()

    # Migrate forward
    create_governance_tables(db_path)
    create_adjudication_tables(db_path)

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row

    # Verify banned column added to agent_registry
    gov_cols = {
        r["name"] for r in conn.execute("PRAGMA table_info(agent_registry)").fetchall()
    }
    assert "banned" in gov_cols

    # Verify new adjudication columns added
    adj_cols = {
        r["name"] for r in conn.execute("PRAGMA table_info(adjudication_decision)").fetchall()
    }
    assert "frozen_at" in adj_cols
    assert "manual_extension" in adj_cols
    assert "issued_by_did" in adj_cols

    # Verify new tables exist
    tables = {
        r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }
    assert "adjudicator_registry" in tables
    assert "impeachment" in tables
    assert "watchdog_anomaly" in tables

    conn.close()
