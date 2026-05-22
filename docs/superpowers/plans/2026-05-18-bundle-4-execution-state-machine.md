# Bundle 4 — Execution State Machine Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace v0.2.x's flat `task_assignment.status` strings (`pending/approved/committed/executing/completed/failed`) with a real 9-state spec-faithful execution state machine, plus a 7-stage execution pipeline. Lands `mitosis-oasis` at version **0.7.0**. Enforces SP-2 (Non-Bypassing) invariant: every task traverses all 7 stages in order, no skipping.

**Architecture:** Two new modules — `oasis/execution/state_machine.py` (9-state enum + transitions + guards, mirrors `governance/state_machine.py`) and `oasis/execution/pipeline.py` (7-stage enum + per-stage adapters). Two new columns on `task_assignment` (`state`, `stage`). All execution endpoints migrate from string comparisons to enum lookups. Runner drives the state machine; pipeline stages are checkpoints inside the EXECUTING state. Largest refactor in the v0.97-parity project: touches every execution endpoint, every execution test fixture, every cross-branch E2E.

**Tech Stack:** Python 3.10-3.11, FastAPI, SQLite, pytest, Pydantic. No new external deps.

**Depends on:** Bundle 1 merged. Independent of Bundles 2/3 (those land in parallel branches).

**Source spec:** [2026-05-18-agentcity-v097-parity-design.md](../specs/2026-05-18-agentcity-v097-parity-design.md) section 2 (Bundle 4), section 5 (rubric EXE-050..056, INV-137).

---

## File Map

**New files (5):**

- `oasis/execution/state_machine.py` — `ExecutionNodeState` enum + `TRANSITIONS` dict + guards
- `oasis/execution/pipeline.py` — `ExecutionStage` enum + adapter functions
- `test/execution/test_state_machine.py`
- `test/execution/test_pipeline.py`
- `test/spec_v097/test_exe_050_nine_node_states.py`
- `test/spec_v097/test_exe_055_frozen_state.py`
- `test/spec_v097/test_inv_137_sp2_non_bypassing.py`

**Modified files (6):**

- `oasis/execution/schema.py` — add `state` + `stage` columns; add CHECK constraints; legacy `status` kept for one minor version as a derived view
- `oasis/execution/runner.py` — drive state_machine + pipeline; replace string comparisons
- `oasis/execution/commitment.py` — use enum transitions
- `oasis/execution/validator.py` — emit `state=PENDING_VERIFICATION` or `PENDING_REVIEW` based on PoP tier
- `oasis/execution/endpoints.py` — enum lookups; expose `state` and `stage` in responses
- `oasis/execution/service.py` — re-export state/pipeline; clean enum boundary

**Extended:**

- `test/e2e/test_full_protocol_smoke.py` — Bundle-4 waypoint (drive a task through all 9 states + 7 stages; assert no skip)

---

## State Machine Reference

```
WAITING ──(all predecessors COMPLETED)──> ELIGIBLE
ELIGIBLE ──(routeTask)──> EXECUTING
EXECUTING ──(submit output, Tier 1/2)──> PENDING_VERIFICATION
EXECUTING ──(submit output, Tier 3)──> PENDING_REVIEW
PENDING_VERIFICATION ──(PoP pass)──> COMPLETED
PENDING_VERIFICATION ──(PoP fail)──> FAILED
PENDING_REVIEW ──(human accept)──> COMPLETED
PENDING_REVIEW ──(human reject)──> FAILED
COMPLETED ──(on-chain anchor confirmed)──> PENDING_FINALIZATION
PENDING_FINALIZATION ──(settlement committed)──> COMPLETED   (terminal)
ANY ──(Guardian freeze)──> FROZEN
FROZEN ──(adjudicator unfreeze)──> ELIGIBLE | FAILED
EXECUTING ──(timeout)──> FAILED
```

Plus illegal transitions (rejected by guards):

- WAITING → EXECUTING (must go through ELIGIBLE)
- EXECUTING → COMPLETED (must go through PENDING_VERIFICATION or PENDING_REVIEW)
- ELIGIBLE → COMPLETED (no skipping verification)

## Pipeline Stage Reference

Inside the EXECUTING state, the runner advances through 7 stages in strict order:

```
Orchestrate → Invoke → Commit → Guard → Verify → Gate → Record
```

- **Orchestrate**: code-hash verification, capability match check.
- **Invoke**: dispatch to agent (LLM or synthetic).
- **Commit**: agent submits output + Merkle root of audit trail.
- **Guard**: behavioural-deviation detection (σ-threshold).
- **Verify**: PoP tier 1 / 2 / 3 verification (moves state to PENDING\_\*).
- **Gate**: constitutional-output-predicate (STATICCALL-style) checks.
- **Record**: anchored to event_log (Bundle 3 anchor picks it up next interval).

SP-2 invariant: skipping any stage is rejected by `_next_stage()` (Task 3).

---

## Task 1: Schema migration — `state` + `stage` columns

**Files:**

- Modify: `oasis/execution/schema.py`

- [ ] **Step 1.1: Add the columns + idempotent ALTER block**

Append to `create_execution_tables()`:

```python
    # Bundle 4: 9-state execution machine + 7-stage pipeline.
    for stmt in (
        "ALTER TABLE task_assignment ADD COLUMN state TEXT "
        "CHECK(state IN ('WAITING', 'ELIGIBLE', 'EXECUTING', "
        "'PENDING_VERIFICATION', 'PENDING_REVIEW', 'COMPLETED', "
        "'FROZEN', 'FAILED', 'PENDING_FINALIZATION'))",
        "ALTER TABLE task_assignment ADD COLUMN stage TEXT "
        "CHECK(stage IN ('ORCHESTRATE', 'INVOKE', 'COMMIT', 'GUARD', "
        "'VERIFY', 'GATE', 'RECORD'))",
        # Audit trail of state transitions
        "CREATE TABLE IF NOT EXISTS task_state_transition ("
        "  transition_id INTEGER PRIMARY KEY AUTOINCREMENT,"
        "  task_id TEXT NOT NULL,"
        "  from_state TEXT,"
        "  to_state TEXT NOT NULL,"
        "  from_stage TEXT,"
        "  to_stage TEXT,"
        "  reason TEXT,"
        "  transitioned_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,"
        "  FOREIGN KEY (task_id) REFERENCES task_assignment(task_id)"
        ")",
    ):
        try:
            conn.execute(stmt)
        except sqlite3.OperationalError:
            pass  # column/table exists
```

- [ ] **Step 1.2: Schema test**

Create `test/execution/test_schema_bundle4.py`:

```python
"""Bundle 4 schema additions."""
import sqlite3
from pathlib import Path

import pytest

from oasis.execution.schema import create_execution_tables


def test_task_assignment_has_state_column(tmp_path):
    p = tmp_path / "exec.db"
    create_execution_tables(str(p))
    conn = sqlite3.connect(str(p))
    cols = {r[1] for r in conn.execute("PRAGMA table_info(task_assignment)")}
    assert "state" in cols
    assert "stage" in cols


def test_state_check_constraint_rejects_invalid(tmp_path):
    p = tmp_path / "exec.db"
    create_execution_tables(str(p))
    conn = sqlite3.connect(str(p))
    conn.execute(
        "INSERT INTO task_assignment "
        "(task_id, session_id, node_id, agent_did, state) "
        "VALUES ('t1', 's1', 'n1', 'a1', 'WAITING')"
    )
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "UPDATE task_assignment SET state = 'INVALID_STATE' WHERE task_id = 't1'"
        )


def test_task_state_transition_table_present(tmp_path):
    p = tmp_path / "exec.db"
    create_execution_tables(str(p))
    conn = sqlite3.connect(str(p))
    tables = {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    )}
    assert "task_state_transition" in tables
```

Run + commit:

```bash
pytest test/execution/test_schema_bundle4.py -v
git add oasis/execution/schema.py test/execution/test_schema_bundle4.py
git commit -m "feat(execution): Bundle 4 schema — state + stage columns + transition table"
```

---

## Task 2: `oasis/execution/state_machine.py` (TDD)

**Files:**

- Create: `oasis/execution/state_machine.py`
- Create: `test/execution/test_state_machine.py`
- Create: `test/spec_v097/test_exe_050_nine_node_states.py`
- Create: `test/spec_v097/test_exe_055_frozen_state.py`

- [ ] **Step 2.1: Write failing tests**

Create `test/execution/test_state_machine.py`:

```python
"""9-state execution machine. Mirrors governance/state_machine.py pattern."""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from oasis.execution.state_machine import (
    ExecutionNodeState,
    TRANSITIONS,
    can_transition,
    GuardResult,
    transition,
)
from oasis.execution.schema import create_execution_tables
from oasis.governance.schema import create_governance_tables


@pytest.fixture
def exec_db(tmp_path):
    g = tmp_path / "g.db"
    p = tmp_path / "exec.db"
    create_governance_tables(str(g))
    create_execution_tables(str(p))
    return str(p)


def test_all_nine_states_defined():
    expected = {
        "WAITING", "ELIGIBLE", "EXECUTING",
        "PENDING_VERIFICATION", "PENDING_REVIEW",
        "COMPLETED", "FROZEN", "FAILED", "PENDING_FINALIZATION",
    }
    actual = {s.value for s in ExecutionNodeState}
    assert actual == expected


def test_legal_transition_waiting_to_eligible(exec_db):
    _seed_task(exec_db, task_id="t1", state="WAITING")
    result = can_transition(
        task_id="t1",
        from_state=ExecutionNodeState.WAITING,
        to_state=ExecutionNodeState.ELIGIBLE,
        db_path=exec_db,
    )
    assert result.allowed is True


def test_illegal_transition_waiting_to_executing_blocked(exec_db):
    _seed_task(exec_db, task_id="t1", state="WAITING")
    result = can_transition(
        task_id="t1",
        from_state=ExecutionNodeState.WAITING,
        to_state=ExecutionNodeState.EXECUTING,
        db_path=exec_db,
    )
    assert result.allowed is False
    assert "transition" in result.reason.lower() or "guard" in result.reason.lower()


def test_illegal_transition_executing_to_completed_blocked(exec_db):
    """Must traverse PENDING_VERIFICATION or PENDING_REVIEW first."""
    _seed_task(exec_db, task_id="t1", state="EXECUTING")
    result = can_transition(
        task_id="t1",
        from_state=ExecutionNodeState.EXECUTING,
        to_state=ExecutionNodeState.COMPLETED,
        db_path=exec_db,
    )
    assert result.allowed is False


def test_frozen_can_transition_from_any_state(exec_db):
    for s in ("ELIGIBLE", "EXECUTING", "PENDING_VERIFICATION"):
        _seed_task(exec_db, task_id=f"t-{s}", state=s)
        result = can_transition(
            task_id=f"t-{s}",
            from_state=ExecutionNodeState(s),
            to_state=ExecutionNodeState.FROZEN,
            db_path=exec_db,
        )
        assert result.allowed is True, f"FROZEN unreachable from {s}"


def test_transition_writes_audit_row(exec_db):
    _seed_task(exec_db, task_id="t1", state="WAITING")
    transition(
        task_id="t1",
        to_state=ExecutionNodeState.ELIGIBLE,
        reason="all predecessors completed",
        db_path=exec_db,
    )
    conn = sqlite3.connect(exec_db)
    row = conn.execute(
        "SELECT from_state, to_state FROM task_state_transition WHERE task_id = 't1'"
    ).fetchone()
    assert row == ("WAITING", "ELIGIBLE")


def _seed_task(db: str, task_id: str, state: str):
    conn = sqlite3.connect(db)
    conn.execute(
        "INSERT INTO task_assignment "
        "(task_id, session_id, node_id, agent_did, state) "
        "VALUES (?, 's1', 'n1', 'a1', ?)",
        (task_id, state),
    )
    conn.commit()
    conn.close()
```

Create `test/spec_v097/test_exe_050_nine_node_states.py`:

```python
"""Spec exec §0.4: nine node states present in code."""
from oasis.execution.state_machine import ExecutionNodeState


def test_nine_states_exactly():
    names = {s.value for s in ExecutionNodeState}
    assert names == {
        "WAITING", "ELIGIBLE", "EXECUTING",
        "PENDING_VERIFICATION", "PENDING_REVIEW",
        "COMPLETED", "FROZEN", "FAILED", "PENDING_FINALIZATION",
    }, f"expected exactly 9 spec states, got {names}"
```

Create `test/spec_v097/test_exe_055_frozen_state.py`:

```python
"""Spec exec §0.4 + adj §2.4: FROZEN state reachable from any operational
state. Recovery requires adjudicator action (unfreeze → ELIGIBLE; or
confirm → FAILED)."""
from oasis.execution.state_machine import TRANSITIONS, ExecutionNodeState


def test_frozen_is_reachable_from_operational_states():
    for from_state in (
        ExecutionNodeState.ELIGIBLE,
        ExecutionNodeState.EXECUTING,
        ExecutionNodeState.PENDING_VERIFICATION,
        ExecutionNodeState.PENDING_REVIEW,
    ):
        assert ExecutionNodeState.FROZEN in TRANSITIONS[from_state], (
            f"FROZEN must be reachable from {from_state.value}"
        )


def test_frozen_can_go_to_eligible_or_failed():
    nexts = TRANSITIONS[ExecutionNodeState.FROZEN]
    assert ExecutionNodeState.ELIGIBLE in nexts
    assert ExecutionNodeState.FAILED in nexts
```

- [ ] **Step 2.2: Implement `oasis/execution/state_machine.py`**

```python
"""Nine-state execution state machine (spec exec §0.4).

Mirrors oasis/governance/state_machine.py structurally:
  - ExecutionNodeState enum (9 values)
  - TRANSITIONS: dict of legal next-states
  - can_transition: structural check + guard evaluation
  - transition: applies a state change, writes audit row, optionally
    emits event_bus event.

Predecessor-completion guards live on WAITING → ELIGIBLE; verification
guards live on PENDING_* → COMPLETED.
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Callable


class ExecutionNodeState(str, Enum):
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
        ExecutionNodeState.FAILED,  # timeout
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
        ExecutionNodeState.COMPLETED,  # re-enter terminal after anchor confirms
    },
    ExecutionNodeState.FROZEN: {
        ExecutionNodeState.ELIGIBLE,   # unfreeze
        ExecutionNodeState.FAILED,     # confirm freeze
    },
    ExecutionNodeState.FAILED: set(),  # terminal
}


@dataclass
class GuardResult:
    allowed: bool
    reason: str = ""


def _guard_waiting_to_eligible(task_id: str, conn: sqlite3.Connection,
                                 **ctx) -> GuardResult:
    """All predecessor nodes must be in COMPLETED state."""
    preds = conn.execute(
        "SELECT predecessor_node_id FROM dag_edge "
        "INNER JOIN task_assignment ta ON ta.task_id = ? "
        "WHERE dag_edge.successor_node_id = ta.node_id",
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
    (ExecutionNodeState.WAITING, ExecutionNodeState.ELIGIBLE): _guard_waiting_to_eligible,
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
```

- [ ] **Step 2.3: Run + commit**

Run: `pytest test/execution/test_state_machine.py test/spec_v097/test_exe_050_nine_node_states.py test/spec_v097/test_exe_055_frozen_state.py -v`
Expected: 11 passed.

```bash
git add oasis/execution/state_machine.py test/execution/test_state_machine.py test/spec_v097/test_exe_050_nine_node_states.py test/spec_v097/test_exe_055_frozen_state.py
git commit -m "feat(execution/state_machine): 9-state execution machine (spec exec §0.4)"
```

---

## Task 3: `oasis/execution/pipeline.py` — 7-stage pipeline (TDD)

**Files:**

- Create: `oasis/execution/pipeline.py`
- Create: `test/execution/test_pipeline.py`
- Create: `test/spec_v097/test_inv_137_sp2_non_bypassing.py`

- [ ] **Step 3.1: Write failing tests**

Create `test/execution/test_pipeline.py`:

```python
"""7-stage pipeline. Stages traversed strictly in order; no skipping."""
from oasis.execution.pipeline import (
    ExecutionStage,
    next_stage,
    PIPELINE_ORDER,
    is_legal_advance,
)


def test_seven_stages_defined():
    expected = ["ORCHESTRATE", "INVOKE", "COMMIT", "GUARD",
                 "VERIFY", "GATE", "RECORD"]
    actual = [s.value for s in ExecutionStage]
    assert actual == expected
    assert PIPELINE_ORDER == [ExecutionStage(s) for s in expected]


def test_next_stage_orchestrate_invoke():
    assert next_stage(ExecutionStage.ORCHESTRATE) == ExecutionStage.INVOKE


def test_next_stage_record_returns_none():
    assert next_stage(ExecutionStage.RECORD) is None


def test_is_legal_advance_only_to_immediate_next():
    assert is_legal_advance(ExecutionStage.ORCHESTRATE, ExecutionStage.INVOKE) is True
    assert is_legal_advance(ExecutionStage.ORCHESTRATE, ExecutionStage.COMMIT) is False
    assert is_legal_advance(ExecutionStage.GUARD, ExecutionStage.VERIFY) is True
    assert is_legal_advance(ExecutionStage.GUARD, ExecutionStage.RECORD) is False


def test_initial_stage_is_orchestrate():
    assert PIPELINE_ORDER[0] == ExecutionStage.ORCHESTRATE
```

Create `test/spec_v097/test_inv_137_sp2_non_bypassing.py`:

```python
"""Spec invariant SP-2: every task execution traverses the complete
seven-stage pipeline. No skips allowed."""
import pytest

from oasis.execution.pipeline import (
    ExecutionStage,
    is_legal_advance,
    PIPELINE_ORDER,
)


def test_skipping_a_stage_is_rejected():
    for i, current in enumerate(PIPELINE_ORDER[:-2]):
        skip_target = PIPELINE_ORDER[i + 2]
        assert is_legal_advance(current, skip_target) is False, (
            f"SP-2 violated: {current.value} → {skip_target.value} not rejected"
        )


def test_full_pipeline_traversal_is_legal():
    """The legal full traversal exists end-to-end."""
    for current, nxt in zip(PIPELINE_ORDER[:-1], PIPELINE_ORDER[1:]):
        assert is_legal_advance(current, nxt) is True
```

- [ ] **Step 3.2: Implement `oasis/execution/pipeline.py`**

```python
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
    INVOKE = "INVOKE"            # dispatch to agent
    COMMIT = "COMMIT"            # agent submits output + Merkle root
    GUARD = "GUARD"              # behavioural-deviation detection
    VERIFY = "VERIFY"            # PoP tier 1/2/3 verification
    GATE = "GATE"                # constitutional output predicates
    RECORD = "RECORD"            # anchor into event_log


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


def is_legal_advance(current: ExecutionStage,
                      candidate: ExecutionStage) -> bool:
    """SP-2 enforcement: candidate must be the immediate next stage."""
    return next_stage(current) == candidate


def advance_stage(
    *,
    task_id: str,
    to_stage: ExecutionStage,
    db_path: str | Path,
) -> None:
    """Apply a stage advance after is_legal_advance has passed.
    Records the transition in task_state_transition."""
    conn = sqlite3.connect(str(db_path))
    try:
        row = conn.execute(
            "SELECT stage FROM task_assignment WHERE task_id = ?",
            (task_id,),
        ).fetchone()
        from_stage = row[0] if row else None
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
```

- [ ] **Step 3.3: Run + commit**

Run: `pytest test/execution/test_pipeline.py test/spec_v097/test_inv_137_sp2_non_bypassing.py -v`
Expected: 7 passed.

```bash
git add oasis/execution/pipeline.py test/execution/test_pipeline.py test/spec_v097/test_inv_137_sp2_non_bypassing.py
git commit -m "feat(execution/pipeline): 7-stage pipeline + SP-2 non-bypassing invariant"
```

---

## Task 4: Migrate runner.py to enum-based state

**Files:**

- Modify: `oasis/execution/runner.py`
- Modify: `oasis/execution/commitment.py`
- Modify: `oasis/execution/validator.py`

The strategy: keep `status` column writes for one minor version as a legacy alias, while adding `state` column writes alongside. New callers read `state`; legacy callers still see `status`. After Bundle 4 ships, Bundle 5 (or a follow-up cleanup PR) drops the `status` column.

- [ ] **Step 4.1: Add a translation helper**

Append to `oasis/execution/state_machine.py`:

```python
# Legacy alias: maps the old `status` string to the new state enum.
LEGACY_STATUS_TO_STATE: dict[str, ExecutionNodeState] = {
    "pending":   ExecutionNodeState.WAITING,
    "approved":  ExecutionNodeState.ELIGIBLE,
    "committed": ExecutionNodeState.ELIGIBLE,    # post-stake-lock
    "executing": ExecutionNodeState.EXECUTING,
    "completed": ExecutionNodeState.COMPLETED,
    "failed":    ExecutionNodeState.FAILED,
}

# Reverse — for keeping the legacy `status` column in sync.
STATE_TO_LEGACY_STATUS: dict[ExecutionNodeState, str] = {
    ExecutionNodeState.WAITING: "pending",
    ExecutionNodeState.ELIGIBLE: "committed",
    ExecutionNodeState.EXECUTING: "executing",
    ExecutionNodeState.PENDING_VERIFICATION: "executing",
    ExecutionNodeState.PENDING_REVIEW: "executing",
    ExecutionNodeState.COMPLETED: "completed",
    ExecutionNodeState.PENDING_FINALIZATION: "completed",
    ExecutionNodeState.FROZEN: "failed",
    ExecutionNodeState.FAILED: "failed",
}
```

Update `transition()` to also write the legacy `status`:

```python
        legacy = STATE_TO_LEGACY_STATUS.get(to_state, "")
        conn.execute(
            "UPDATE task_assignment SET state = ?, status = ? WHERE task_id = ?",
            (to_state.value, legacy, task_id),
        )
```

- [ ] **Step 4.2: Migrate `commitment.py`**

In `oasis/execution/commitment.py`, the existing `commit_to_task()` does:

```python
"UPDATE task_assignment SET status = 'committed' WHERE task_id = ?"
```

Replace with a call to `state_machine.transition()`:

```python
from oasis.execution.state_machine import ExecutionNodeState, transition

transition(
    task_id=task_id,
    to_state=ExecutionNodeState.ELIGIBLE,  # ELIGIBLE = post-stake-lock
    reason="stake committed",
    db_path=db_path,
)
```

Read sites that compare `status` against `"approved"` or `"committed"` should be migrated to read `state` and compare against the enum.

- [ ] **Step 4.3: Migrate `runner.py`**

Current `runner.py` flow:

- line 64: `if task["status"] != "committed": ...` → check `state == ExecutionNodeState.ELIGIBLE`
- line 72: `UPDATE task_assignment SET status = 'executing'` → `transition(to_state=EXECUTING, reason="routeTask")`
- line 200-207: terminal `completed/failed` writes → `transition()` calls; but **add intermediate PENDING_VERIFICATION or PENDING_REVIEW first**.

Specifically: when the agent submits an output (`receive_output()` path), do not jump straight to `completed/failed`. Instead, transition to `PENDING_VERIFICATION` (Tier 1/2) or `PENDING_REVIEW` (Tier 3) based on the DAG node's `pop_tier`:

```python
from oasis.execution.state_machine import ExecutionNodeState, transition

# Read the DAG node's pop_tier from governance/dag_node
pop_tier = _get_pop_tier(task_id, db_path)
if pop_tier == 3:
    transition(task_id=task_id, to_state=ExecutionNodeState.PENDING_REVIEW,
                reason="Tier 3 output submitted", db_path=db_path)
else:
    transition(task_id=task_id, to_state=ExecutionNodeState.PENDING_VERIFICATION,
                reason=f"Tier {pop_tier} output submitted", db_path=db_path)
```

`_get_pop_tier(task_id, db_path)` joins task_assignment → dag_node via `node_id`.

- [ ] **Step 4.4: Migrate `validator.py`**

After validation passes/fails, transition `PENDING_VERIFICATION → COMPLETED` or `PENDING_VERIFICATION → FAILED`:

```python
from oasis.execution.state_machine import ExecutionNodeState, transition

if validation_passed:
    transition(task_id=task_id, to_state=ExecutionNodeState.COMPLETED,
                reason="PoP validation passed", db_path=db_path)
else:
    transition(task_id=task_id, to_state=ExecutionNodeState.FAILED,
                reason="PoP validation failed", db_path=db_path)
```

- [ ] **Step 4.5: Run all execution tests; align failures**

Run: `pytest test/execution/ -v`
Expected: many tests fail because they (a) checked `status` directly, (b) didn't expect a PENDING_VERIFICATION intermediate state, (c) bypassed transition() and wrote `status = 'completed'` directly.

For each failure:

1. If the test asserts `status == 'X'`, also assert `state == ExecutionNodeState.Y` (use the legacy map).
2. If the test bypassed the state machine, refactor to call `transition()`.
3. If the test expected `executing → completed` directly, insert an intermediate `PENDING_VERIFICATION → COMPLETED` step.

Run: `pytest test/execution/ -v` → all pass.

```bash
git add oasis/execution/runner.py oasis/execution/commitment.py oasis/execution/validator.py oasis/execution/state_machine.py test/execution/
git commit -m "refactor(execution): migrate runner/commitment/validator to state machine"
```

---

## Task 5: Endpoint migration

**Files:**

- Modify: `oasis/execution/endpoints.py`

- [ ] **Step 5.1: Update endpoint responses**

Every execution endpoint that returns `status` should also return `state` and `stage`:

```python
@router.get("/tasks/{task_id}")
async def get_task(task_id: str):
    conn = sqlite3.connect(_get_db())
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        "SELECT task_id, session_id, node_id, agent_did, state, stage, "
        "status, created_at FROM task_assignment WHERE task_id = ?",
        (task_id,),
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail=f"task {task_id} not found")
    return dict(row)
```

Add a new endpoint to retrieve the full transition audit:

```python
@router.get("/tasks/{task_id}/transitions")
async def get_task_transitions(task_id: str):
    conn = sqlite3.connect(_get_db())
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT * FROM task_state_transition WHERE task_id = ? "
        "ORDER BY transitioned_at ASC",
        (task_id,),
    ).fetchall()
    return [dict(r) for r in rows]
```

- [ ] **Step 5.2: Run cross-branch tests**

Run: `pytest test/cross_branch/ -v`
Expected: any test that asserts the old `status` shape needs an update. For each, prefer reading `state` going forward.

```bash
git add oasis/execution/endpoints.py test/cross_branch/
git commit -m "feat(execution/endpoints): expose state + stage; add transitions endpoint"
```

---

## Task 6: E2E waypoint + version bump + CHANGELOG

- [ ] **Step 6.1: Bundle-4 E2E waypoint**

Append to `test/e2e/test_full_protocol_smoke.py`:

```python
def test_bundle4_full_state_machine_traversal(tmp_path):
    """Drive a single task from WAITING through every state to
    COMPLETED via PENDING_VERIFICATION. Assert task_state_transition
    audit row exists for each step."""
    from oasis.execution.schema import create_execution_tables
    from oasis.execution.state_machine import (
        ExecutionNodeState, transition, can_transition,
    )
    import sqlite3

    db = tmp_path / "exec.db"
    create_execution_tables(str(db))

    # Seed task in WAITING
    conn = sqlite3.connect(str(db))
    conn.execute(
        "INSERT INTO task_assignment "
        "(task_id, session_id, node_id, agent_did, state) "
        "VALUES ('smoke-t1', 's1', 'n1', 'a1', 'WAITING')"
    )
    conn.commit()
    conn.close()

    # WAITING → ELIGIBLE (no predecessors)
    transition(task_id="smoke-t1", to_state=ExecutionNodeState.ELIGIBLE,
                reason="root node", db_path=str(db))

    # ELIGIBLE → EXECUTING
    transition(task_id="smoke-t1", to_state=ExecutionNodeState.EXECUTING,
                reason="routeTask", db_path=str(db))

    # EXECUTING → PENDING_VERIFICATION (Tier 1)
    transition(task_id="smoke-t1",
                to_state=ExecutionNodeState.PENDING_VERIFICATION,
                reason="Tier 1 output submitted", db_path=str(db))

    # PENDING_VERIFICATION → COMPLETED
    transition(task_id="smoke-t1", to_state=ExecutionNodeState.COMPLETED,
                reason="PoP passed", db_path=str(db))

    # Verify audit trail
    conn = sqlite3.connect(str(db))
    rows = conn.execute(
        "SELECT from_state, to_state FROM task_state_transition "
        "WHERE task_id = 'smoke-t1' ORDER BY transitioned_at ASC"
    ).fetchall()
    assert rows == [
        ("WAITING", "ELIGIBLE"),
        ("ELIGIBLE", "EXECUTING"),
        ("EXECUTING", "PENDING_VERIFICATION"),
        ("PENDING_VERIFICATION", "COMPLETED"),
    ]


def test_bundle4_illegal_skip_rejected(tmp_path):
    """Try to skip from EXECUTING straight to COMPLETED. Must be rejected."""
    from oasis.execution.schema import create_execution_tables
    from oasis.execution.state_machine import (
        ExecutionNodeState, can_transition,
    )
    import sqlite3

    db = tmp_path / "exec.db"
    create_execution_tables(str(db))
    conn = sqlite3.connect(str(db))
    conn.execute(
        "INSERT INTO task_assignment "
        "(task_id, session_id, node_id, agent_did, state) "
        "VALUES ('t-skip', 's1', 'n1', 'a1', 'EXECUTING')"
    )
    conn.commit()
    conn.close()

    result = can_transition(
        task_id="t-skip",
        from_state=ExecutionNodeState.EXECUTING,
        to_state=ExecutionNodeState.COMPLETED,
        db_path=str(db),
    )
    assert result.allowed is False, "SP-2 violation must be rejected"
```

- [ ] **Step 6.2: Version bump + CHANGELOG**

`pyproject.toml`: `0.6.0` → `0.7.0`. `typed_data.py` DOMAIN → `0.7.0`.

Prepend to `CHANGELOG.md`:

```markdown
## [0.7.0] — TBD — Bundle 4 (Execution State Machine)

### Added

- **9-state execution machine** (spec exec §0.4):
  WAITING, ELIGIBLE, EXECUTING, PENDING_VERIFICATION, PENDING_REVIEW,
  COMPLETED, FROZEN, FAILED, PENDING_FINALIZATION. Explicit TRANSITIONS
  table + guards mirror `governance/state_machine.py`.
- **7-stage pipeline** (spec exec §0.4): Orchestrate → Invoke → Commit
  → Guard → Verify → Gate → Record. SP-2 non-bypassing invariant
  enforced (`is_legal_advance` rejects skips).
- New columns: `task_assignment.state`, `task_assignment.stage`.
- New table: `task_state_transition` (audit trail).
- New endpoint: `GET /api/execution/tasks/{task_id}/transitions`.
- New spec_v097 tests: EXE-050, EXE-055, INV-137.

### Breaking

- `task_assignment.status` still written for one minor version (legacy
  alias map in `state_machine.py`), but new code should read `state`.
  Bundle 5 drops `status`.
- Output submission no longer transitions directly to `completed`;
  task moves through `PENDING_VERIFICATION` (Tier 1/2) or
  `PENDING_REVIEW` (Tier 3) first.
- SP-2 enforced: any caller attempting to skip a pipeline stage now
  returns `GuardResult(allowed=False)`.
```

- [ ] **Step 6.3: Full suite + commit**

```bash
pytest -q
git add pyproject.toml CHANGELOG.md oasis/crypto/typed_data.py test/e2e/test_full_protocol_smoke.py
git commit -m "chore(release): v0.7.0 — Bundle 4 (Execution State Machine)"
```

---

## Acceptance Gates

- [ ] All prior tests pass.
- [ ] All Bundle 4 spec_v097 tests pass (EXE-050, EXE-055, INV-137).
- [ ] 9 states + 7 stages enumerated; SP-2 invariant test green.
- [ ] task_assignment.state CHECK constraint enforced.
- [ ] Every state transition recorded in task_state_transition.
- [ ] Codex outside-voice review on the bundle's diff returns no new findings beyond spec.

## Bundle 4 → Bundle 5 handoff

Bundle 5 depends on:

- `ExecutionNodeState.FAILED` exists and can be reached from `EXECUTING` or `PENDING_VERIFICATION`.
- `task_state_transition` table exists (Bundle 5 hooks into it for adaptive refinement).
- The legacy `status` alias still works (Bundle 5 will be the cleanup PR that drops it).

Bundle 5 subscribes to FAILED transitions via the event bus and triggers adaptive refinement child sessions.
