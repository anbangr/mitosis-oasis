"""P1 — Test constitution parameter seeding and updates."""
import sqlite3
from pathlib import Path

import pytest

from oasis.governance.schema import create_governance_tables, seed_constitution


EXPECTED_PARAMS = {
    "budget_cap_max": 1_000_000.0,
    "budget_cap_min": 1.0,
    "quorum_threshold": 0.51,
    "max_deliberation_rounds": 3.0,
    "reputation_floor": 0.1,
    "fairness_hhi_threshold": 0.25,
    "proposal_deadline_max_ms": 86_400_000.0,
    "voting_method": 1.0,
    "max_dag_depth": 10.0,
    "max_dag_nodes": 50.0,
}


def _connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA foreign_keys = ON")
    conn.row_factory = sqlite3.Row
    return conn


def test_default_params_seeded(db_path: Path):
    """seed_constitution inserts all 10 default parameters."""
    create_governance_tables(db_path)
    seed_constitution(db_path)
    conn = _connect(db_path)
    rows = conn.execute("SELECT param_name FROM constitution").fetchall()
    conn.close()
    assert len(rows) == 10


def test_all_params_present(db_path: Path):
    """Every expected parameter name exists."""
    create_governance_tables(db_path)
    seed_constitution(db_path)
    conn = _connect(db_path)
    rows = conn.execute("SELECT param_name FROM constitution").fetchall()
    conn.close()
    names = {r["param_name"] for r in rows}
    assert names == set(EXPECTED_PARAMS.keys())


def test_value_ranges_correct(db_path: Path):
    """Parameter values match expected defaults."""
    create_governance_tables(db_path)
    seed_constitution(db_path)
    conn = _connect(db_path)
    for name, expected_val in EXPECTED_PARAMS.items():
        row = conn.execute(
            "SELECT param_value FROM constitution WHERE param_name = ?",
            (name,),
        ).fetchone()
        assert row is not None, f"Missing param: {name}"
        assert row["param_value"] == pytest.approx(expected_val), (
            f"{name}: expected {expected_val}, got {row['param_value']}"
        )
    conn.close()


def test_param_update_works(db_path: Path):
    """Updating an existing parameter value succeeds."""
    create_governance_tables(db_path)
    seed_constitution(db_path)
    conn = _connect(db_path)
    conn.execute(
        "UPDATE constitution SET param_value = ? WHERE param_name = ?",
        (0.67, "quorum_threshold"),
    )
    conn.commit()
    row = conn.execute(
        "SELECT param_value FROM constitution WHERE param_name = 'quorum_threshold'"
    ).fetchone()
    conn.close()
    assert row["param_value"] == pytest.approx(0.67)


def test_seed_idempotent(db_path: Path):
    """Calling seed_constitution twice does not duplicate rows."""
    create_governance_tables(db_path)
    seed_constitution(db_path)
    seed_constitution(db_path)  # second call
    conn = _connect(db_path)
    rows = conn.execute("SELECT COUNT(*) AS cnt FROM constitution").fetchone()
    conn.close()
    assert rows["cnt"] == 10
