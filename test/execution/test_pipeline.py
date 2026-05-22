"""Seven-stage execution pipeline (spec exec §0.4).

Strict-order traversal inside the EXECUTING state. SP-2 invariant
(Non-Bypassing): no stage may be skipped.

Stage adapters are hooks where downstream code (validator, anchor
publisher) can plug in. Bundle 4 provides the structure; the actual
behaviour of each stage lives in existing modules (runner,
synthetic, validator, guardian).
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from oasis.execution.pipeline import (
    ExecutionStage,
    PIPELINE_ORDER,
    next_stage,
    is_legal_advance,
    advance_stage,
)


# ---------------------------------------------------------------------------
# Stage enum & order
# ---------------------------------------------------------------------------


def test_seven_stages_defined() -> None:
    expected = [
        "ORCHESTRATE",
        "INVOKE",
        "COMMIT",
        "GUARD",
        "VERIFY",
        "GATE",
        "RECORD",
    ]
    actual = [s.value for s in ExecutionStage]
    assert actual == expected


def test_pipeline_order_matches_enum_sequence() -> None:
    expected = [
        ExecutionStage(s)
        for s in [
            "ORCHESTRATE",
            "INVOKE",
            "COMMIT",
            "GUARD",
            "VERIFY",
            "GATE",
            "RECORD",
        ]
    ]
    assert PIPELINE_ORDER == expected


def test_initial_stage_is_orchestrate() -> None:
    assert PIPELINE_ORDER[0] == ExecutionStage.ORCHESTRATE


def test_record_is_last_stage() -> None:
    assert PIPELINE_ORDER[-1] == ExecutionStage.RECORD


# ---------------------------------------------------------------------------
# next_stage()
# ---------------------------------------------------------------------------


def test_next_stage_orchestrate_to_invoke() -> None:
    assert next_stage(ExecutionStage.ORCHESTRATE) == ExecutionStage.INVOKE


def test_next_stage_invoke_to_commit() -> None:
    assert next_stage(ExecutionStage.INVOKE) == ExecutionStage.COMMIT


def test_next_stage_commit_to_guard() -> None:
    assert next_stage(ExecutionStage.COMMIT) == ExecutionStage.GUARD


def test_next_stage_guard_to_verify() -> None:
    assert next_stage(ExecutionStage.GUARD) == ExecutionStage.VERIFY


def test_next_stage_verify_to_gate() -> None:
    assert next_stage(ExecutionStage.VERIFY) == ExecutionStage.GATE


def test_next_stage_gate_to_record() -> None:
    assert next_stage(ExecutionStage.GATE) == ExecutionStage.RECORD


def test_next_stage_record_returns_none() -> None:
    assert next_stage(ExecutionStage.RECORD) is None


# ---------------------------------------------------------------------------
# is_legal_advance()
# ---------------------------------------------------------------------------


def test_is_legal_advance_orchestrate_to_invoke() -> None:
    assert is_legal_advance(ExecutionStage.ORCHESTRATE, ExecutionStage.INVOKE) is True


def test_is_legal_advance_invoke_to_commit() -> None:
    assert is_legal_advance(ExecutionStage.INVOKE, ExecutionStage.COMMIT) is True


def test_is_legal_advance_commit_to_guard() -> None:
    assert is_legal_advance(ExecutionStage.COMMIT, ExecutionStage.GUARD) is True


def test_is_legal_advance_guard_to_verify() -> None:
    assert is_legal_advance(ExecutionStage.GUARD, ExecutionStage.VERIFY) is True


def test_is_legal_advance_verify_to_gate() -> None:
    assert is_legal_advance(ExecutionStage.VERIFY, ExecutionStage.GATE) is True


def test_is_legal_advance_gate_to_record() -> None:
    assert is_legal_advance(ExecutionStage.GATE, ExecutionStage.RECORD) is True


def test_is_legal_advance_orchestrate_to_commit_is_false() -> None:
    assert is_legal_advance(ExecutionStage.ORCHESTRATE, ExecutionStage.COMMIT) is False


def test_is_legal_advance_guard_to_record_is_false() -> None:
    assert is_legal_advance(ExecutionStage.GUARD, ExecutionStage.RECORD) is False


def test_is_legal_advance_same_stage_is_false() -> None:
    assert (
        is_legal_advance(ExecutionStage.ORCHESTRATE, ExecutionStage.ORCHESTRATE)
        is False
    )


def test_is_legal_advance_backward_is_false() -> None:
    assert is_legal_advance(ExecutionStage.INVOKE, ExecutionStage.ORCHESTRATE) is False


# ---------------------------------------------------------------------------
# advance_stage()
# ---------------------------------------------------------------------------


def _seed_task_assignment(db: str | Path, task_id: str, stage: str) -> None:
    """Insert a minimal task_assignment row, bypassing FK constraints."""
    conn = sqlite3.connect(str(db))
    conn.execute("PRAGMA foreign_keys = OFF")
    conn.execute(
        "INSERT INTO task_assignment "
        "(task_id, session_id, node_id, agent_did, stage) "
        "VALUES (?, 's1', 'n1', 'a1', ?)",
        (task_id, stage),
    )
    conn.commit()
    conn.close()


def test_advance_stage_updates_task_assignment(tmp_path: Path) -> None:
    db = tmp_path / "exec.db"
    from oasis.execution.schema import create_execution_tables

    create_execution_tables(str(db))
    _seed_task_assignment(db, "t1", "ORCHESTRATE")

    advance_stage(task_id="t1", to_stage=ExecutionStage.INVOKE, db_path=db)

    conn = sqlite3.connect(str(db))
    row = conn.execute(
        "SELECT stage FROM task_assignment WHERE task_id = 't1'"
    ).fetchone()
    conn.close()
    assert row[0] == "INVOKE"


def test_advance_stage_records_audit_row(tmp_path: Path) -> None:
    db = tmp_path / "exec.db"
    from oasis.execution.schema import create_execution_tables

    create_execution_tables(str(db))
    _seed_task_assignment(db, "t1", "ORCHESTRATE")

    advance_stage(task_id="t1", to_stage=ExecutionStage.INVOKE, db_path=db)

    conn = sqlite3.connect(str(db))
    row = conn.execute(
        "SELECT from_stage, to_stage FROM task_state_transition WHERE task_id = 't1'"
    ).fetchone()
    conn.close()
    assert row == ("ORCHESTRATE", "INVOKE")


def test_advance_stage_records_from_stage_when_no_prior_stage(tmp_path: Path) -> None:
    db = tmp_path / "exec.db"
    from oasis.execution.schema import create_execution_tables

    create_execution_tables(str(db))
    _seed_task_assignment(db, "t1", "ORCHESTRATE")

    advance_stage(task_id="t1", to_stage=ExecutionStage.INVOKE, db_path=db)

    conn = sqlite3.connect(str(db))
    row = conn.execute(
        "SELECT from_stage, to_stage FROM task_state_transition WHERE task_id = 't1'"
    ).fetchone()
    conn.close()
    assert row[0] == "ORCHESTRATE"
    assert row[1] == "INVOKE"


def test_advance_stage_multiple_transitions_create_multiple_audit_rows(
    tmp_path: Path,
) -> None:
    db = tmp_path / "exec.db"
    from oasis.execution.schema import create_execution_tables

    create_execution_tables(str(db))
    _seed_task_assignment(db, "t1", "ORCHESTRATE")

    advance_stage(task_id="t1", to_stage=ExecutionStage.INVOKE, db_path=db)
    advance_stage(task_id="t1", to_stage=ExecutionStage.COMMIT, db_path=db)

    conn = sqlite3.connect(str(db))
    rows = conn.execute(
        "SELECT from_stage, to_stage FROM task_state_transition WHERE task_id = 't1' ORDER BY transition_id"
    ).fetchall()
    conn.close()
    assert len(rows) == 2
    assert rows[0] == ("ORCHESTRATE", "INVOKE")
    assert rows[1] == ("INVOKE", "COMMIT")


def test_advance_stage_nonexistent_task_raises(tmp_path: Path) -> None:
    db = tmp_path / "exec.db"
    from oasis.execution.schema import create_execution_tables

    create_execution_tables(str(db))

    with pytest.raises(Exception):
        advance_stage(task_id="missing", to_stage=ExecutionStage.INVOKE, db_path=db)
