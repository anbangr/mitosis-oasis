"""Tests for execution module migration to state_machine transitions.

Covers the test spec from Phase 4.1:
- T1: commit_to_task invokes transition() → state ELIGIBLE, legacy status committed
- T2: runner rejects tasks not in ELIGIBLE state
- T3: runner routes pop_tier == 3 → PENDING_REVIEW, others → PENDING_VERIFICATION
- Validator transitions to COMPLETED or FAILED
- Legacy status column stays in sync on every transition
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from oasis.config import PlatformConfig
from oasis.execution.commitment import commit_to_task
from oasis.execution.router import route_tasks
from oasis.execution.runner import ExecutionDispatcher
from oasis.execution.validator import OutputValidator

from .conftest import drive_to_deployed


@pytest.fixture()
def llm_config() -> PlatformConfig:
    return PlatformConfig(execution_mode="llm")


class TestCommitmentMigration:
    def test_commit_to_task_transitions_state_to_eligible(
        self, execution_db: Path, deployed_session: dict
    ) -> None:
        """T1: commit_to_task() calls transition() → state ELIGIBLE."""
        sid = deployed_session["session_id"]
        assignments = route_tasks(sid, execution_db)
        task = assignments[0]

        commit_to_task(task["task_id"], task["agent_did"], execution_db)

        conn = sqlite3.connect(str(execution_db))
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT state, status FROM task_assignment WHERE task_id = ?",
            (task["task_id"],),
        ).fetchone()
        audit = conn.execute(
            "SELECT from_state, to_state, reason FROM task_state_transition "
            "WHERE task_id = ? ORDER BY transition_id DESC LIMIT 1",
            (task["task_id"],),
        ).fetchone()
        conn.close()

        assert row["state"] == "ELIGIBLE"
        assert row["status"] == "committed"
        assert audit is not None
        assert audit["from_state"] == "WAITING"
        assert audit["to_state"] == "ELIGIBLE"
        assert "stake committed" in audit["reason"]


class TestRunnerMigration:
    def test_dispatch_rejects_task_not_eligible(
        self, execution_db: Path, llm_config: PlatformConfig
    ) -> None:
        """T2: Runner rejects a task whose state is not ELIGIBLE."""
        conn = sqlite3.connect(str(execution_db))
        conn.execute("PRAGMA foreign_keys = OFF")
        conn.execute(
            "INSERT INTO task_assignment "
            "(task_id, session_id, node_id, agent_did, status, state) "
            "VALUES (?, 's1', 'n1', 'a1', 'committed', 'WAITING')",
            ("t-not-eligible",),
        )
        conn.commit()
        conn.close()

        dispatcher = ExecutionDispatcher(llm_config, execution_db)
        with pytest.raises(ValueError, match="ELIGIBLE"):
            dispatcher.dispatch_task("t-not-eligible")

    def test_receive_output_tier3_goes_to_pending_review(
        self, execution_db: Path, producers: list[dict], llm_config: PlatformConfig
    ) -> None:
        """T3: pop_tier == 3 routes to PENDING_REVIEW."""
        info = drive_to_deployed(execution_db, producers)
        tasks = route_tasks(info["session_id"], execution_db)
        task = tasks[0]

        # Set the dag_node pop_tier to 3 for this task
        conn = sqlite3.connect(str(execution_db))
        conn.execute(
            "UPDATE dag_node SET pop_tier = 3 WHERE node_id = ?",
            (task["node_id"],),
        )
        conn.commit()
        conn.close()

        commit_to_task(task["task_id"], task["agent_did"], execution_db)
        dispatcher = ExecutionDispatcher(llm_config, execution_db)
        dispatcher.dispatch_task(task["task_id"])

        output_data = json.dumps(
            {
                "task_id": task["task_id"],
                "result": "test-result",
                "status": "success",
                "metrics": {"accuracy": 0.9, "completeness": 0.95},
            }
        )
        dispatcher.receive_output(task["task_id"], output_data, task["agent_did"])

        conn = sqlite3.connect(str(execution_db))
        conn.row_factory = sqlite3.Row
        audit = conn.execute(
            "SELECT to_state, reason FROM task_state_transition "
            "WHERE task_id = ? AND to_state = 'PENDING_REVIEW'",
            (task["task_id"],),
        ).fetchone()
        conn.close()

        assert audit is not None
        assert "Tier 3" in audit["reason"] or "tier 3" in audit["reason"].lower()

    def test_receive_output_tier1_goes_to_pending_verification(
        self, execution_db: Path, producers: list[dict], llm_config: PlatformConfig
    ) -> None:
        """T3: pop_tier != 3 routes to PENDING_VERIFICATION."""
        info = drive_to_deployed(execution_db, producers)
        tasks = route_tasks(info["session_id"], execution_db)
        task = tasks[0]

        # Ensure pop_tier is 1 (default)
        conn = sqlite3.connect(str(execution_db))
        conn.execute(
            "UPDATE dag_node SET pop_tier = 1 WHERE node_id = ?",
            (task["node_id"],),
        )
        conn.commit()
        conn.close()

        commit_to_task(task["task_id"], task["agent_did"], execution_db)
        dispatcher = ExecutionDispatcher(llm_config, execution_db)
        dispatcher.dispatch_task(task["task_id"])

        output_data = json.dumps(
            {
                "task_id": task["task_id"],
                "result": "test-result",
                "status": "success",
                "metrics": {"accuracy": 0.9, "completeness": 0.95},
            }
        )
        dispatcher.receive_output(task["task_id"], output_data, task["agent_did"])

        conn = sqlite3.connect(str(execution_db))
        conn.row_factory = sqlite3.Row
        audit = conn.execute(
            "SELECT to_state, reason FROM task_state_transition "
            "WHERE task_id = ? AND to_state = 'PENDING_VERIFICATION'",
            (task["task_id"],),
        ).fetchone()
        conn.close()

        assert audit is not None
        assert "Tier 1" in audit["reason"] or "tier 1" in audit["reason"].lower()


class TestValidatorMigration:
    def test_validator_pass_transitions_to_completed(self, execution_db: Path) -> None:
        """Validator transitions task state to COMPLETED on passing validation."""
        conn = sqlite3.connect(str(execution_db))
        conn.execute("PRAGMA foreign_keys = OFF")
        conn.execute(
            "INSERT INTO task_assignment "
            "(task_id, session_id, node_id, agent_did, status, state) "
            "VALUES (?, 's1', 'n1', 'a1', 'executing', 'PENDING_VERIFICATION')",
            ("t-val-pass",),
        )
        conn.execute(
            "INSERT INTO dag_node (node_id, proposal_id, label, service_id, pop_tier, "
            "token_budget, timeout_ms) VALUES ('n1', 'p1', 'node', 'svc', 1, 100.0, 60000)"
        )
        conn.commit()
        conn.close()

        validator = OutputValidator()
        output = {
            "output_data": json.dumps(
                {
                    "task_id": "t-val-pass",
                    "result": "good",
                    "status": "success",
                    "metrics": {"accuracy": 0.9, "completeness": 0.95},
                }
            ),
            "latency_ms": 100,
        }
        validator.validate("t-val-pass", output, execution_db)

        conn = sqlite3.connect(str(execution_db))
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT state FROM task_assignment WHERE task_id = ?",
            ("t-val-pass",),
        ).fetchone()
        audit = conn.execute(
            "SELECT from_state, to_state, reason FROM task_state_transition "
            "WHERE task_id = ? AND to_state = 'COMPLETED'",
            ("t-val-pass",),
        ).fetchone()
        conn.close()

        assert row["state"] == "COMPLETED"
        assert audit is not None
        assert audit["from_state"] == "PENDING_VERIFICATION"
        assert "PoP validation passed" in audit["reason"]

    def test_validator_fail_transitions_to_failed(self, execution_db: Path) -> None:
        """Validator transitions task state to FAILED on failing validation."""
        conn = sqlite3.connect(str(execution_db))
        conn.execute("PRAGMA foreign_keys = OFF")
        conn.execute(
            "INSERT INTO task_assignment "
            "(task_id, session_id, node_id, agent_did, status, state) "
            "VALUES (?, 's1', 'n1', 'a1', 'executing', 'PENDING_VERIFICATION')",
            ("t-val-fail",),
        )
        conn.execute(
            "INSERT INTO dag_node (node_id, proposal_id, label, service_id, pop_tier, "
            "token_budget, timeout_ms) VALUES ('n1', 'p1', 'node', 'svc', 1, 100.0, 60000)"
        )
        conn.commit()
        conn.close()

        validator = OutputValidator()
        output = {
            "output_data": json.dumps({"bad_field": True}),
            "latency_ms": 100,
        }
        validator.validate("t-val-fail", output, execution_db)

        conn = sqlite3.connect(str(execution_db))
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT state FROM task_assignment WHERE task_id = ?",
            ("t-val-fail",),
        ).fetchone()
        audit = conn.execute(
            "SELECT from_state, to_state, reason FROM task_state_transition "
            "WHERE task_id = ? AND to_state = 'FAILED'",
            ("t-val-fail",),
        ).fetchone()
        conn.close()

        assert row["state"] == "FAILED"
        assert audit is not None
        assert audit["from_state"] == "PENDING_VERIFICATION"
        assert "PoP validation failed" in audit["reason"]
