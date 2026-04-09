"""Tests for ExecutionDispatcher in synthetic mode."""
from __future__ import annotations

import pytest

from oasis.config import PlatformConfig
from oasis.execution.commitment import commit_to_task
from oasis.execution.router import route_tasks
from oasis.execution.runner import ExecutionDispatcher

from .conftest import drive_to_deployed


@pytest.fixture()
def syn_config() -> PlatformConfig:
    return PlatformConfig(execution_mode="synthetic", synthetic_quality="perfect")


@pytest.fixture()
def syn_dispatcher(syn_config, execution_db):
    return ExecutionDispatcher(syn_config, execution_db)


@pytest.fixture()
def committed_task(execution_db, producers, syn_dispatcher):
    info = drive_to_deployed(execution_db, producers)
    tasks = route_tasks(info["session_id"], execution_db)
    assert len(tasks) > 0
    task = tasks[0]
    commit_to_task(task["task_id"], task["agent_did"], execution_db)
    return task


class TestRunnerSyntheticMode:
    def test_synthetic_output_generated(self, syn_dispatcher, committed_task):
        """In synthetic mode, dispatch generates output without agent interaction."""
        result = syn_dispatcher.dispatch_task(committed_task["task_id"])
        assert result["mode"] == "synthetic"
        assert result["status"] in ("completed", "failed")

    def test_synthetic_output_stored(self, syn_dispatcher, committed_task):
        """After synthetic dispatch, output record exists in DB."""
        syn_dispatcher.dispatch_task(committed_task["task_id"])
        status = syn_dispatcher.get_task_status(committed_task["task_id"])
        assert status.has_output is True

    def test_synthetic_status_completed(self, syn_dispatcher, committed_task):
        """Perfect-quality synthetic dispatch completes the task."""
        result = syn_dispatcher.dispatch_task(committed_task["task_id"])
        assert result["status"] == "completed"
        status = syn_dispatcher.get_task_status(committed_task["task_id"])
        assert status.status == "completed"
