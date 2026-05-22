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
from enum import Enum
from pathlib import Path


class ExecutionStage(str, Enum):
    ORCHESTRATE = "ORCHESTRATE"  # code-hash verify, capability match
    INVOKE = "INVOKE"  # dispatch to agent
    COMMIT = "COMMIT"  # agent submits output + Merkle root
    GUARD = "GUARD"  # behavioural-deviation detection
    VERIFY = "VERIFY"  # PoP tier 1/2/3 verification
    GATE = "GATE"  # constitutional output predicates
    RECORD = "RECORD"  # anchor into event_log


PIPELINE_ORDER: list[ExecutionStage] = [
    ExecutionStage.ORCHESTRATE,
    ExecutionStage.INVOKE,
    ExecutionStage.COMMIT,
    ExecutionStage.GUARD,
    ExecutionStage.VERIFY,
    ExecutionStage.GATE,
    ExecutionStage.RECORD,
]


def next_stage(current: ExecutionStage) -> ExecutionStage | None:
    """Return the next stage in canonical order, or None if at RECORD."""
    idx = PIPELINE_ORDER.index(current)
    if idx + 1 < len(PIPELINE_ORDER):
        return PIPELINE_ORDER[idx + 1]
    return None


def is_legal_advance(
    current: ExecutionStage,
    candidate: ExecutionStage,
) -> bool:
    """SP-2 enforcement: candidate must be the immediate next stage."""
    return next_stage(current) == candidate


def advance_stage(
    *,
    task_id: str,
    to_stage: ExecutionStage,
    db_path: str | Path,
) -> None:
    """Apply a stage advance after is_legal_advance has passed.

    Records the transition in task_state_transition.
    Raises if the task_id does not exist in task_assignment.
    """
    conn = sqlite3.connect(str(db_path))
    try:
        row = conn.execute(
            "SELECT stage FROM task_assignment WHERE task_id = ?",
            (task_id,),
        ).fetchone()
        if row is None:
            raise ValueError(f"Task {task_id!r} not found in task_assignment")
        from_stage = row[0]
        conn.execute(
            "UPDATE task_assignment SET stage = ? WHERE task_id = ?",
            (to_stage.value, task_id),
        )
        conn.execute(
            "INSERT INTO task_state_transition "
            "(task_id, from_stage, to_stage) VALUES (?, ?, ?)",
            (task_id, from_stage, to_stage.value),
        )
        conn.commit()
    finally:
        conn.close()
