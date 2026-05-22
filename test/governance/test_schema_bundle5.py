"""Bundle 5 — Test petition tables, session trigger columns, and constitution params."""

import sqlite3
from pathlib import Path

import pytest

from oasis.governance.schema import create_governance_tables, seed_constitution


BUNDLE5_TABLES = {"petition", "petition_signature", "evidence_anchor"}
BUNDLE5_PARAMS = {
    "sponsorship_min": (5.0, "integer"),
    "milestone_round_interval": (20.0, "integer"),
    "petition_threshold": (0.20, "float"),
    "adaptive_iteration_budget": (3.0, "integer"),
}


def _connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA foreign_keys = ON")
    conn.row_factory = sqlite3.Row
    return conn


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
    ).fetchone()
    return row is not None


def _get_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return {r["name"] for r in rows}


# ---------------------------------------------------------------------------
# T1 — Petition tables created
# ---------------------------------------------------------------------------


def test_petition_table_exists(db_path: Path):
    """create_governance_tables creates the petition table."""
    create_governance_tables(db_path)
    conn = _connect(db_path)
    assert _table_exists(conn, "petition")
    conn.close()


def test_petition_signature_table_exists(db_path: Path):
    """create_governance_tables creates the petition_signature table."""
    create_governance_tables(db_path)
    conn = _connect(db_path)
    assert _table_exists(conn, "petition_signature")
    conn.close()


def test_evidence_anchor_table_exists(db_path: Path):
    """create_governance_tables creates the evidence_anchor table."""
    create_governance_tables(db_path)
    conn = _connect(db_path)
    assert _table_exists(conn, "evidence_anchor")
    conn.close()


def test_all_bundle5_tables_created(db_path: Path):
    """All three Bundle-5 tables are present after init."""
    create_governance_tables(db_path)
    conn = _connect(db_path)
    tables = {
        r[0]
        for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }
    assert BUNDLE5_TABLES.issubset(tables)
    conn.close()


# ---------------------------------------------------------------------------
# T2 — Session trigger columns present
# ---------------------------------------------------------------------------


def test_session_trigger_column_exists(db_path: Path):
    """legislative_session has a 'trigger' column."""
    create_governance_tables(db_path)
    conn = _connect(db_path)
    cols = _get_columns(conn, "legislative_session")
    assert "trigger" in cols
    conn.close()


def test_session_parent_task_id_column_exists(db_path: Path):
    """legislative_session has a 'parent_task_id' column."""
    create_governance_tables(db_path)
    conn = _connect(db_path)
    cols = _get_columns(conn, "legislative_session")
    assert "parent_task_id" in cols
    conn.close()


def test_session_iteration_column_exists(db_path: Path):
    """legislative_session has an 'iteration' column."""
    create_governance_tables(db_path)
    conn = _connect(db_path)
    cols = _get_columns(conn, "legislative_session")
    assert "iteration" in cols
    conn.close()


def test_session_all_trigger_columns_present(db_path: Path):
    """legislative_session has trigger, parent_task_id, and iteration."""
    create_governance_tables(db_path)
    conn = _connect(db_path)
    cols = _get_columns(conn, "legislative_session")
    assert {"trigger", "parent_task_id", "iteration"}.issubset(cols)
    conn.close()


# ---------------------------------------------------------------------------
# T3 — Constitution defaults seeded
# ---------------------------------------------------------------------------


def test_bundle5_constitution_params_seeded(db_path: Path):
    """seed_constitution inserts all four Bundle-5 parameters."""
    create_governance_tables(db_path)
    seed_constitution(db_path)
    conn = _connect(db_path)
    for name, (expected_val, _) in BUNDLE5_PARAMS.items():
        row = conn.execute(
            "SELECT param_value FROM constitution WHERE param_name = ?", (name,)
        ).fetchone()
        assert row is not None, f"Missing param: {name}"
        assert row["param_value"] == pytest.approx(expected_val), (
            f"{name}: expected {expected_val}, got {row['param_value']}"
        )
    conn.close()


def test_bundle5_constitution_param_types(db_path: Path):
    """Bundle-5 params have correct param_type values."""
    create_governance_tables(db_path)
    seed_constitution(db_path)
    conn = _connect(db_path)
    for name, (_, expected_type) in BUNDLE5_PARAMS.items():
        row = conn.execute(
            "SELECT param_type FROM constitution WHERE param_name = ?", (name,)
        ).fetchone()
        assert row is not None, f"Missing param: {name}"
        assert row["param_type"] == expected_type
    conn.close()


def test_sponsorship_min_value(db_path: Path):
    """sponsorship_min defaults to 5.0."""
    create_governance_tables(db_path)
    seed_constitution(db_path)
    conn = _connect(db_path)
    row = conn.execute(
        "SELECT param_value FROM constitution WHERE param_name = 'sponsorship_min'"
    ).fetchone()
    conn.close()
    assert row["param_value"] == pytest.approx(5.0)


def test_milestone_round_interval_value(db_path: Path):
    """milestone_round_interval defaults to 20.0."""
    create_governance_tables(db_path)
    seed_constitution(db_path)
    conn = _connect(db_path)
    row = conn.execute(
        "SELECT param_value FROM constitution WHERE param_name = 'milestone_round_interval'"
    ).fetchone()
    conn.close()
    assert row["param_value"] == pytest.approx(20.0)


def test_petition_threshold_value(db_path: Path):
    """petition_threshold defaults to 0.20."""
    create_governance_tables(db_path)
    seed_constitution(db_path)
    conn = _connect(db_path)
    row = conn.execute(
        "SELECT param_value FROM constitution WHERE param_name = 'petition_threshold'"
    ).fetchone()
    conn.close()
    assert row["param_value"] == pytest.approx(0.20)


def test_adaptive_iteration_budget_value(db_path: Path):
    """adaptive_iteration_budget defaults to 3.0."""
    create_governance_tables(db_path)
    seed_constitution(db_path)
    conn = _connect(db_path)
    row = conn.execute(
        "SELECT param_value FROM constitution WHERE param_name = 'adaptive_iteration_budget'"
    ).fetchone()
    conn.close()
    assert row["param_value"] == pytest.approx(3.0)


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


def test_idempotent_recreation_with_bundle5_alters(db_path: Path):
    """Calling create_governance_tables twice does not raise on idempotent ALTERs."""
    create_governance_tables(db_path)
    create_governance_tables(db_path)  # should not raise
    conn = _connect(db_path)
    assert _table_exists(conn, "petition")
    assert _table_exists(conn, "petition_signature")
    assert _table_exists(conn, "evidence_anchor")
    cols = _get_columns(conn, "legislative_session")
    assert {"trigger", "parent_task_id", "iteration"}.issubset(cols)
    conn.close()


def test_trigger_default_is_manual(db_path: Path):
    """When trigger is omitted on INSERT, default is 'manual'."""
    create_governance_tables(db_path)
    conn = _connect(db_path)
    conn.execute(
        "INSERT INTO legislative_session (session_id, mission_budget_cap) "
        "VALUES (?, ?)",
        ("sess-trigger-default", 1000.0),
    )
    conn.commit()
    row = conn.execute(
        "SELECT trigger FROM legislative_session WHERE session_id = ?",
        ("sess-trigger-default",),
    ).fetchone()
    conn.close()
    assert row["trigger"] == "manual"


def test_iteration_default_is_zero(db_path: Path):
    """When iteration is omitted on INSERT, default is 0."""
    create_governance_tables(db_path)
    conn = _connect(db_path)
    conn.execute(
        "INSERT INTO legislative_session (session_id, mission_budget_cap) "
        "VALUES (?, ?)",
        ("sess-iteration-default", 1000.0),
    )
    conn.commit()
    row = conn.execute(
        "SELECT iteration FROM legislative_session WHERE session_id = ?",
        ("sess-iteration-default",),
    ).fetchone()
    conn.close()
    assert row["iteration"] == 0
