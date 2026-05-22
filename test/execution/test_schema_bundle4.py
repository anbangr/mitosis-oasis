"""Bundle 4 schema additions — 9-state execution machine + 7-stage pipeline."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from oasis.execution.schema import create_execution_tables

VALID_STATES = (
    "WAITING",
    "ELIGIBLE",
    "EXECUTING",
    "PENDING_VERIFICATION",
    "PENDING_REVIEW",
    "COMPLETED",
    "FROZEN",
    "FAILED",
    "PENDING_FINALIZATION",
)

VALID_STAGES = (
    "ORCHESTRATE",
    "INVOKE",
    "COMMIT",
    "GUARD",
    "VERIFY",
    "GATE",
    "RECORD",
)


def _insert_minimal_task(conn: sqlite3.Connection, task_id: str = "t1") -> None:
    """Insert a minimal task_assignment row (FK checks disabled externally)."""
    conn.execute(
        "INSERT INTO task_assignment (task_id, session_id, node_id, agent_did) "
        "VALUES (?, 's1', 'n1', 'a1')",
        (task_id,),
    )


def _setup_conn_for_insert(p: Path) -> sqlite3.Connection:
    """Create DB, insert minimal row bypassing FK constraints."""
    create_execution_tables(str(p))
    conn = sqlite3.connect(str(p))
    conn.execute("PRAGMA foreign_keys = OFF")
    _insert_minimal_task(conn)
    conn.commit()
    return conn


# ---------------------------------------------------------------------------
# T1 — happy path
# ---------------------------------------------------------------------------


def test_task_assignment_has_state_and_stage_columns(tmp_path: Path) -> None:
    """Fresh database: state and stage columns exist on task_assignment."""
    p = tmp_path / "exec.db"
    create_execution_tables(str(p))
    conn = sqlite3.connect(str(p))
    cols = {r[1] for r in conn.execute("PRAGMA table_info(task_assignment)")}
    conn.close()
    assert "state" in cols
    assert "stage" in cols


def test_task_state_transition_table_present(tmp_path: Path) -> None:
    """Fresh database: task_state_transition audit table exists."""
    p = tmp_path / "exec.db"
    create_execution_tables(str(p))
    conn = sqlite3.connect(str(p))
    tables = {
        r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }
    conn.close()
    assert "task_state_transition" in tables


def test_task_state_transition_schema(tmp_path: Path) -> None:
    """task_state_transition has the expected columns and types."""
    p = tmp_path / "exec.db"
    create_execution_tables(str(p))
    conn = sqlite3.connect(str(p))
    cols = {
        r[1]: r[2] for r in conn.execute("PRAGMA table_info(task_state_transition)")
    }
    conn.close()
    assert cols.get("transition_id") == "INTEGER"
    assert cols.get("task_id") == "TEXT"
    assert cols.get("from_state") == "TEXT"
    assert cols.get("to_state") == "TEXT"
    assert cols.get("from_stage") == "TEXT"
    assert cols.get("to_stage") == "TEXT"
    assert cols.get("reason") == "TEXT"
    assert cols.get("transitioned_at") == "TIMESTAMP"


def test_task_state_transition_has_fk_to_task_assignment(tmp_path: Path) -> None:
    """task_state_transition has a foreign key referencing task_assignment."""
    p = tmp_path / "exec.db"
    create_execution_tables(str(p))
    conn = sqlite3.connect(str(p))
    fks = conn.execute("PRAGMA foreign_key_list(task_state_transition)").fetchall()
    conn.close()
    fk_targets = {(fk[2], fk[3]) for fk in fks}
    assert ("task_assignment", "task_id") in fk_targets


# ---------------------------------------------------------------------------
# T2 — error case (CHECK constraints)
# ---------------------------------------------------------------------------


def test_state_check_constraint_accepts_all_valid_values(tmp_path: Path) -> None:
    """All 9 valid state values are accepted by the CHECK constraint."""
    p = tmp_path / "exec.db"
    conn = _setup_conn_for_insert(p)
    for state in VALID_STATES:
        conn.execute(
            "UPDATE task_assignment SET state = ? WHERE task_id = 't1'",
            (state,),
        )
    conn.commit()
    conn.close()


@pytest.mark.parametrize("bad_state", ["INVALID_STATE", "waiting", "DONE", ""])
def test_state_check_constraint_rejects_invalid(tmp_path: Path, bad_state: str) -> None:
    """Invalid state values raise IntegrityError."""
    p = tmp_path / "exec.db"
    conn = _setup_conn_for_insert(p)
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "UPDATE task_assignment SET state = ? WHERE task_id = 't1'",
            (bad_state,),
        )
    conn.close()


def test_stage_check_constraint_accepts_all_valid_values(tmp_path: Path) -> None:
    """All 7 valid stage values are accepted by the CHECK constraint."""
    p = tmp_path / "exec.db"
    conn = _setup_conn_for_insert(p)
    for stage in VALID_STAGES:
        conn.execute(
            "UPDATE task_assignment SET stage = ? WHERE task_id = 't1'",
            (stage,),
        )
    conn.commit()
    conn.close()


@pytest.mark.parametrize("bad_stage", ["INVALID_STAGE", "orchestrate", "DONE", ""])
def test_stage_check_constraint_rejects_invalid(tmp_path: Path, bad_stage: str) -> None:
    """Invalid stage values raise IntegrityError."""
    p = tmp_path / "exec.db"
    conn = _setup_conn_for_insert(p)
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "UPDATE task_assignment SET stage = ? WHERE task_id = 't1'",
            (bad_stage,),
        )
    conn.close()


# ---------------------------------------------------------------------------
# T3 — idempotency
# ---------------------------------------------------------------------------


def test_idempotent_re_execution(tmp_path: Path) -> None:
    """Calling create_execution_tables twice does not raise OperationalError."""
    p = tmp_path / "exec.db"
    create_execution_tables(str(p))
    create_execution_tables(str(p))  # should not raise
    conn = sqlite3.connect(str(p))
    cols = {r[1] for r in conn.execute("PRAGMA table_info(task_assignment)")}
    tables = {
        r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }
    conn.close()
    assert "state" in cols
    assert "stage" in cols
    assert "task_state_transition" in tables
