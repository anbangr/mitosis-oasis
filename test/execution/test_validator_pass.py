"""Tests for OutputValidator — valid outputs pass all checks."""
from __future__ import annotations

import json
import sqlite3

import pytest

from oasis.execution.router import route_tasks
from oasis.execution.validator import OutputValidator

from .conftest import drive_to_deployed


@pytest.fixture()
def validator() -> OutputValidator:
    return OutputValidator()


@pytest.fixture()
def routed_task(execution_db, producers):
    info = drive_to_deployed(execution_db, producers)
    tasks = route_tasks(info["session_id"], execution_db)
    assert len(tasks) > 0
    return tasks[0]


class TestValidatorPass:
    def test_valid_output_passes_all(self, validator, routed_task, execution_db):
        """A valid output passes schema, timeout, and quality checks."""
        output = {
            "output_data": json.dumps({
                "task_id": routed_task["task_id"],
                "result": "test-result",
                "status": "success",
                "metrics": {"accuracy": 0.9, "completeness": 0.95},
            }),
            "latency_ms": 100,
        }
        result = validator.validate(routed_task["task_id"], output, execution_db)
        assert result.schema_valid is True
        assert result.timeout_valid is True

    def test_no_guardian_alert_for_valid(self, validator, routed_task, execution_db):
        """No guardian alert is emitted for a valid output."""
        output = {
            "output_data": json.dumps({
                "task_id": routed_task["task_id"],
                "result": "good-result",
                "status": "success",
                "metrics": {"accuracy": 0.85, "completeness": 0.9},
            }),
            "latency_ms": 50,
        }
        result = validator.validate(routed_task["task_id"], output, execution_db)
        assert result.guardian_alert is None

    def test_quality_score_populated(self, validator, routed_task, execution_db):
        """Quality score is computed and > 0 for valid outputs."""
        output = {
            "output_data": json.dumps({
                "task_id": routed_task["task_id"],
                "result": "quality-result",
                "status": "success",
                "metrics": {"accuracy": 0.92, "completeness": 0.88},
            }),
            "latency_ms": 75,
        }
        result = validator.validate(routed_task["task_id"], output, execution_db)
        assert result.quality_score > 0.0
        # Average of 0.92 and 0.88 = 0.9
        assert abs(result.quality_score - 0.9) < 0.01
