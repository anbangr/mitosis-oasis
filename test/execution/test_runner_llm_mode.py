"""Tests for ExecutionDispatcher in LLM mode."""
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
def llm_config() -> PlatformConfig:
    return PlatformConfig(execution_mode="llm")


@pytest.fixture()
def llm_dispatcher(llm_config, execution_db):
    return ExecutionDispatcher(llm_config, execution_db)


@pytest.fixture()
def committed_task(execution_db, producers, llm_dispatcher):
    """Create and commit a task, return (task, dispatcher)."""
    info = drive_to_deployed(execution_db, producers)
    tasks = route_tasks(info["session_id"], execution_db)
    assert len(tasks) > 0
    task = tasks[0]
    commit_to_task(task["task_id"], task["agent_did"], execution_db)
    return task


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestRunnerLLMMode:
    def test_dispatch_sets_executing(self, llm_dispatcher, committed_task):
        """Dispatching in LLM mode sets task status to 'executing'."""
        result = llm_dispatcher.dispatch_task(committed_task["task_id"])
        assert result["mode"] == "llm"
        assert result["status"] == "executing"

        status = llm_dispatcher.get_task_status(committed_task["task_id"])
        assert status.status == "executing"

    def test_dispatch_status_is_executing(self, llm_dispatcher, committed_task):
        """After dispatch, get_task_status returns 'executing'."""
        llm_dispatcher.dispatch_task(committed_task["task_id"])
        status = llm_dispatcher.get_task_status(committed_task["task_id"])
        assert status.status == "executing"
        assert status.has_output is False

    def test_receive_output_stores_and_validates(self, llm_dispatcher, committed_task):
        """Receiving output stores it and triggers validation."""
        llm_dispatcher.dispatch_task(committed_task["task_id"])
        output_data = json.dumps({
            "task_id": committed_task["task_id"],
            "result": "test-result",
            "status": "success",
            "metrics": {"accuracy": 0.9, "completeness": 0.95},
        })
        result = llm_dispatcher.receive_output(
            committed_task["task_id"],
            output_data,
            committed_task["agent_did"],
        )
        assert result["status"] == "completed"
        assert result["validation"]["schema_valid"] is True

    def test_validation_triggered_on_receive(self, llm_dispatcher, committed_task):
        """After receiving output, validation record exists."""
        llm_dispatcher.dispatch_task(committed_task["task_id"])
        output_data = json.dumps({
            "task_id": committed_task["task_id"],
            "result": "test-result",
            "status": "success",
            "metrics": {"accuracy": 0.8, "completeness": 0.9},
        })
        llm_dispatcher.receive_output(
            committed_task["task_id"],
            output_data,
            committed_task["agent_did"],
        )
        status = llm_dispatcher.get_task_status(committed_task["task_id"])
        assert status.has_output is True
        assert status.has_validation is True
