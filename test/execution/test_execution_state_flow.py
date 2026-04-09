"""Tests for full execution state flow: pending → committed → executing → completed/failed."""
from __future__ import annotations

import json

import pytest

from oasis.config import PlatformConfig
from oasis.execution.commitment import commit_to_task
from oasis.execution.router import route_tasks
from oasis.execution.runner import ExecutionDispatcher

from .conftest import drive_to_deployed


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def llm_config():
    return PlatformConfig(execution_mode="llm")


@pytest.fixture()
def syn_config():
    return PlatformConfig(
        execution_mode="synthetic",
        synthetic_quality="perfect",
    )


@pytest.fixture()
def tasks_and_db(execution_db, producers):
    info = drive_to_deployed(execution_db, producers)
    tasks = route_tasks(info["session_id"], execution_db)
    return tasks, execution_db


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestExecutionStateFlow:
    def test_full_flow_success(self, tasks_and_db, llm_config):
        """Full flow: pending → committed → executing → completed."""
        tasks, db = tasks_and_db
        task = tasks[0]
        dispatcher = ExecutionDispatcher(llm_config, db)

        # pending
        status = dispatcher.get_task_status(task["task_id"])
        assert status.status == "pending"

        # → committed
        commit_to_task(task["task_id"], task["agent_did"], db)
        status = dispatcher.get_task_status(task["task_id"])
        assert status.status == "committed"

        # → executing
        dispatcher.dispatch_task(task["task_id"])
        status = dispatcher.get_task_status(task["task_id"])
        assert status.status == "executing"

        # → completed
        output_data = json.dumps({
            "task_id": task["task_id"],
            "result": "final-result",
            "status": "success",
            "metrics": {"accuracy": 0.9, "completeness": 0.9},
        })
        dispatcher.receive_output(task["task_id"], output_data, task["agent_did"])
        status = dispatcher.get_task_status(task["task_id"])
        assert status.status == "completed"

    def test_full_flow_failure(self, tasks_and_db, llm_config):
        """Full flow: pending → committed → executing → failed (bad output)."""
        tasks, db = tasks_and_db
        task = tasks[1] if len(tasks) > 1 else tasks[0]
        dispatcher = ExecutionDispatcher(llm_config, db)

        commit_to_task(task["task_id"], task["agent_did"], db)
        dispatcher.dispatch_task(task["task_id"])

        # Submit output with bad schema
        output_data = json.dumps({"bad_field": True})
        dispatcher.receive_output(task["task_id"], output_data, task["agent_did"])
        status = dispatcher.get_task_status(task["task_id"])
        assert status.status == "failed"

    def test_uncommitted_output_rejected(self, tasks_and_db, llm_config):
        """Cannot submit output for a task that is not committed/executing."""
        tasks, db = tasks_and_db
        task = tasks[0]
        dispatcher = ExecutionDispatcher(llm_config, db)

        with pytest.raises(ValueError, match="expected 'committed'"):
            dispatcher.dispatch_task(task["task_id"])

    def test_frozen_task_blocks_output(self, tasks_and_db, llm_config):
        """A task that has already completed cannot receive more output."""
        tasks, db = tasks_and_db
        task = tasks[0]
        dispatcher = ExecutionDispatcher(llm_config, db)

        # Complete the full flow
        commit_to_task(task["task_id"], task["agent_did"], db)
        dispatcher.dispatch_task(task["task_id"])
        output_data = json.dumps({
            "task_id": task["task_id"],
            "result": "done",
            "status": "success",
            "metrics": {"accuracy": 0.9, "completeness": 0.9},
        })
        dispatcher.receive_output(task["task_id"], output_data, task["agent_did"])

        # Try to submit again — task is now completed
        with pytest.raises(ValueError, match="expected 'executing'"):
            dispatcher.receive_output(task["task_id"], output_data, task["agent_did"])
