"""9-state execution machine. Mirrors governance/state_machine.py pattern."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from oasis.execution.state_machine import (
    ExecutionNodeState,
    TRANSITIONS,
    can_transition,
    transition,
)


def _seed_task(db: str | Path, task_id: str, state: str) -> None:
    """Insert a minimal task_assignment row, bypassing FK constraints."""
    conn = sqlite3.connect(str(db))
    conn.execute("PRAGMA foreign_keys = OFF")
    conn.execute(
        "INSERT INTO task_assignment "
        "(task_id, session_id, node_id, agent_did, state) "
        "VALUES (?, 's1', 'n1', 'a1', ?)",
        (task_id, state),
    )
    conn.commit()
    conn.close()


def test_all_nine_states_defined() -> None:
    expected = {
        "WAITING",
        "ELIGIBLE",
        "EXECUTING",
        "PENDING_VERIFICATION",
        "PENDING_REVIEW",
        "COMPLETED",
        "FROZEN",
        "FAILED",
        "PENDING_FINALIZATION",
    }
    actual = {s.value for s in ExecutionNodeState}
    assert actual == expected


def test_legal_transition_waiting_to_eligible(execution_db: Path) -> None:
    _seed_task(execution_db, task_id="t1", state="WAITING")
    result = can_transition(
        task_id="t1",
        from_state=ExecutionNodeState.WAITING,
        to_state=ExecutionNodeState.ELIGIBLE,
        db_path=execution_db,
    )
    assert result.allowed is True


def test_illegal_transition_waiting_to_executing_blocked(execution_db: Path) -> None:
    _seed_task(execution_db, task_id="t1", state="WAITING")
    result = can_transition(
        task_id="t1",
        from_state=ExecutionNodeState.WAITING,
        to_state=ExecutionNodeState.EXECUTING,
        db_path=execution_db,
    )
    assert result.allowed is False
    assert "transition" in result.reason.lower() or "guard" in result.reason.lower()


def test_illegal_transition_executing_to_completed_blocked(execution_db: Path) -> None:
    """Must traverse PENDING_VERIFICATION or PENDING_REVIEW first."""
    _seed_task(execution_db, task_id="t1", state="EXECUTING")
    result = can_transition(
        task_id="t1",
        from_state=ExecutionNodeState.EXECUTING,
        to_state=ExecutionNodeState.COMPLETED,
        db_path=execution_db,
    )
    assert result.allowed is False


def test_frozen_can_transition_from_any_state(execution_db: Path) -> None:
    for s in ("ELIGIBLE", "EXECUTING", "PENDING_VERIFICATION"):
        _seed_task(execution_db, task_id=f"t-{s}", state=s)
        result = can_transition(
            task_id=f"t-{s}",
            from_state=ExecutionNodeState(s),
            to_state=ExecutionNodeState.FROZEN,
            db_path=execution_db,
        )
        assert result.allowed is True, f"FROZEN unreachable from {s}"


def test_transition_writes_audit_row(execution_db: Path) -> None:
    _seed_task(execution_db, task_id="t1", state="WAITING")
    transition(
        task_id="t1",
        to_state=ExecutionNodeState.ELIGIBLE,
        reason="all predecessors completed",
        db_path=execution_db,
    )
    conn = sqlite3.connect(str(execution_db))
    row = conn.execute(
        "SELECT from_state, to_state FROM task_state_transition WHERE task_id = 't1'"
    ).fetchone()
    conn.close()
    assert row == ("WAITING", "ELIGIBLE")


def test_guard_waiting_to_eligible_blocks_when_predecessors_incomplete(
    execution_db: Path,
) -> None:
    """WAITING → ELIGIBLE guard rejects when predecessors are not COMPLETED."""
    conn = sqlite3.connect(str(execution_db))
    conn.execute("PRAGMA foreign_keys = OFF")
    # Insert a predecessor task and a successor task linked by dag_edge
    conn.execute(
        "INSERT INTO task_assignment (task_id, session_id, node_id, agent_did, state) "
        "VALUES ('pred', 's1', 'pred-node', 'a1', 'EXECUTING')"
    )
    conn.execute(
        "INSERT INTO task_assignment (task_id, session_id, node_id, agent_did, state) "
        "VALUES ('succ', 's1', 'succ-node', 'a1', 'WAITING')"
    )
    conn.execute(
        "INSERT INTO dag_node (node_id, proposal_id, label, service_id, pop_tier, "
        "token_budget, timeout_ms) VALUES ('pred-node', 'p1', 'pred', 'svc', 1, 100.0, 60000)"
    )
    conn.execute(
        "INSERT INTO dag_node (node_id, proposal_id, label, service_id, pop_tier, "
        "token_budget, timeout_ms) VALUES ('succ-node', 'p1', 'succ', 'svc', 1, 100.0, 60000)"
    )
    conn.execute(
        "INSERT INTO dag_edge (proposal_id, from_node_id, to_node_id) "
        "VALUES ('p1', 'pred-node', 'succ-node')"
    )
    conn.commit()
    conn.close()

    result = can_transition(
        task_id="succ",
        from_state=ExecutionNodeState.WAITING,
        to_state=ExecutionNodeState.ELIGIBLE,
        db_path=execution_db,
    )
    assert result.allowed is False
    assert "predecessor" in result.reason.lower()


def test_guard_waiting_to_eligible_allows_when_all_predecessors_completed(
    execution_db: Path,
) -> None:
    """WAITING → ELIGIBLE guard passes when all predecessors are COMPLETED."""
    conn = sqlite3.connect(str(execution_db))
    conn.execute("PRAGMA foreign_keys = OFF")
    conn.execute(
        "INSERT INTO task_assignment (task_id, session_id, node_id, agent_did, state) "
        "VALUES ('pred', 's1', 'pred-node', 'a1', 'COMPLETED')"
    )
    conn.execute(
        "INSERT INTO task_assignment (task_id, session_id, node_id, agent_did, state) "
        "VALUES ('succ', 's1', 'succ-node', 'a1', 'WAITING')"
    )
    conn.execute(
        "INSERT INTO dag_node (node_id, proposal_id, label, service_id, pop_tier, "
        "token_budget, timeout_ms) VALUES ('pred-node', 'p1', 'pred', 'svc', 1, 100.0, 60000)"
    )
    conn.execute(
        "INSERT INTO dag_node (node_id, proposal_id, label, service_id, pop_tier, "
        "token_budget, timeout_ms) VALUES ('succ-node', 'p1', 'succ', 'svc', 1, 100.0, 60000)"
    )
    conn.execute(
        "INSERT INTO dag_edge (proposal_id, from_node_id, to_node_id) "
        "VALUES ('p1', 'pred-node', 'succ-node')"
    )
    conn.commit()
    conn.close()

    result = can_transition(
        task_id="succ",
        from_state=ExecutionNodeState.WAITING,
        to_state=ExecutionNodeState.ELIGIBLE,
        db_path=execution_db,
    )
    assert result.allowed is True


def test_guard_waiting_to_eligible_allows_root_node(execution_db: Path) -> None:
    """Root node with no predecessors can transition WAITING → ELIGIBLE."""
    _seed_task(execution_db, task_id="root", state="WAITING")
    result = can_transition(
        task_id="root",
        from_state=ExecutionNodeState.WAITING,
        to_state=ExecutionNodeState.ELIGIBLE,
        db_path=execution_db,
    )
    assert result.allowed is True


def test_transition_updates_task_assignment_state(execution_db: Path) -> None:
    """transition() updates the state column in task_assignment."""
    _seed_task(execution_db, task_id="t1", state="WAITING")
    transition(
        task_id="t1",
        to_state=ExecutionNodeState.ELIGIBLE,
        reason="ready",
        db_path=execution_db,
    )
    conn = sqlite3.connect(str(execution_db))
    row = conn.execute(
        "SELECT state FROM task_assignment WHERE task_id = 't1'"
    ).fetchone()
    conn.close()
    assert row[0] == "ELIGIBLE"


def test_failed_is_terminal() -> None:
    """FAILED state has no outgoing transitions."""
    assert TRANSITIONS[ExecutionNodeState.FAILED] == set()


def test_completed_to_pending_finalization_allowed(execution_db: Path) -> None:
    _seed_task(execution_db, task_id="t1", state="COMPLETED")
    result = can_transition(
        task_id="t1",
        from_state=ExecutionNodeState.COMPLETED,
        to_state=ExecutionNodeState.PENDING_FINALIZATION,
        db_path=execution_db,
    )
    assert result.allowed is True


def test_pending_finalization_to_completed_allowed(execution_db: Path) -> None:
    _seed_task(execution_db, task_id="t1", state="PENDING_FINALIZATION")
    result = can_transition(
        task_id="t1",
        from_state=ExecutionNodeState.PENDING_FINALIZATION,
        to_state=ExecutionNodeState.COMPLETED,
        db_path=execution_db,
    )
    assert result.allowed is True
