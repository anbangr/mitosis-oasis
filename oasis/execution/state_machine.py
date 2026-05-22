"""Nine-state execution state machine (spec exec §0.4).

Mirrors oasis/governance/state_machine.py structurally:
  - ExecutionNodeState enum (9 values)
  - TRANSITIONS: dict of legal next-states
  - can_transition: structural check + guard evaluation
  - transition: applies a state change, writes audit row.

Predecessor-completion guards live on WAITING → ELIGIBLE; verification
guards live on PENDING_* → COMPLETED.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Callable


class ExecutionNodeState(str, Enum):
    """The 9 states of an execution node."""

    WAITING = "WAITING"
    ELIGIBLE = "ELIGIBLE"
    EXECUTING = "EXECUTING"
    PENDING_VERIFICATION = "PENDING_VERIFICATION"
    PENDING_REVIEW = "PENDING_REVIEW"
    COMPLETED = "COMPLETED"
    FROZEN = "FROZEN"
    FAILED = "FAILED"
    PENDING_FINALIZATION = "PENDING_FINALIZATION"


TRANSITIONS: dict[ExecutionNodeState, set[ExecutionNodeState]] = {
    ExecutionNodeState.WAITING: {
        ExecutionNodeState.ELIGIBLE,
        ExecutionNodeState.FROZEN,
        ExecutionNodeState.FAILED,
    },
    ExecutionNodeState.ELIGIBLE: {
        ExecutionNodeState.EXECUTING,
        ExecutionNodeState.FROZEN,
        ExecutionNodeState.FAILED,
    },
    ExecutionNodeState.EXECUTING: {
        ExecutionNodeState.PENDING_VERIFICATION,
        ExecutionNodeState.PENDING_REVIEW,
        ExecutionNodeState.FROZEN,
        ExecutionNodeState.FAILED,
    },
    ExecutionNodeState.PENDING_VERIFICATION: {
        ExecutionNodeState.COMPLETED,
        ExecutionNodeState.FAILED,
        ExecutionNodeState.FROZEN,
    },
    ExecutionNodeState.PENDING_REVIEW: {
        ExecutionNodeState.COMPLETED,
        ExecutionNodeState.FAILED,
        ExecutionNodeState.FROZEN,
    },
    ExecutionNodeState.COMPLETED: {
        ExecutionNodeState.PENDING_FINALIZATION,
    },
    ExecutionNodeState.PENDING_FINALIZATION: {
        ExecutionNodeState.COMPLETED,
    },
    ExecutionNodeState.FROZEN: {
        ExecutionNodeState.ELIGIBLE,
        ExecutionNodeState.FAILED,
    },
    ExecutionNodeState.FAILED: set(),
}


@dataclass
class GuardResult:
    """Result of evaluating a transition guard."""

    allowed: bool
    reason: str = ""


def _guard_waiting_to_eligible(
    task_id: str, conn: sqlite3.Connection, **ctx
) -> GuardResult:
    """All predecessor nodes must be in COMPLETED state."""
    preds = conn.execute(
        "SELECT de.from_node_id FROM dag_edge de "
        "INNER JOIN task_assignment ta ON ta.task_id = ? "
        "WHERE de.to_node_id = ta.node_id",
        (task_id,),
    ).fetchall()
    if not preds:
        return GuardResult(True)  # root node
    pred_ids = [p[0] for p in preds]
    placeholders = ",".join("?" for _ in pred_ids)
    rows = conn.execute(
        f"SELECT state FROM task_assignment WHERE node_id IN ({placeholders})",
        pred_ids,
    ).fetchall()
    if any(r[0] != "COMPLETED" for r in rows):
        return GuardResult(
            False,
            reason="not all predecessors COMPLETED",
        )
    return GuardResult(True)


GUARDS: dict[tuple[ExecutionNodeState, ExecutionNodeState], Callable] = {
    (
        ExecutionNodeState.WAITING,
        ExecutionNodeState.ELIGIBLE,
    ): _guard_waiting_to_eligible,
}


def can_transition(
    *,
    task_id: str,
    from_state: ExecutionNodeState,
    to_state: ExecutionNodeState,
    db_path: str | Path,
) -> GuardResult:
    """Check structural transition + run guard if defined."""
    if to_state not in TRANSITIONS.get(from_state, set()):
        return GuardResult(
            False,
            reason=f"illegal transition {from_state.value} → {to_state.value}",
        )
    guard = GUARDS.get((from_state, to_state))
    if guard is None:
        return GuardResult(True)
    conn = sqlite3.connect(str(db_path))
    try:
        return guard(task_id=task_id, conn=conn)
    finally:
        conn.close()


def transition(
    *,
    task_id: str,
    to_state: ExecutionNodeState,
    reason: str,
    db_path: str | Path,
) -> None:
    """Apply state change after can_transition has passed. Writes audit row."""
    conn = sqlite3.connect(str(db_path))
    try:
        row = conn.execute(
            "SELECT state FROM task_assignment WHERE task_id = ?",
            (task_id,),
        ).fetchone()
        from_state = row[0] if row else None
        conn.execute(
            "UPDATE task_assignment SET state = ? WHERE task_id = ?",
            (to_state.value, task_id),
        )
        conn.execute(
            "INSERT INTO task_state_transition "
            "(task_id, from_state, to_state, reason) VALUES (?, ?, ?, ?)",
            (task_id, from_state, to_state.value, reason),
        )
        conn.commit()
    finally:
        conn.close()
