"""Tests for OutputValidator — failure cases."""
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


class TestValidatorFail:
    def test_schema_mismatch_detected(self, validator, routed_task, execution_db):
        """Schema mismatch is detected when expected fields are missing."""
        output = {
            "output_data": json.dumps({"wrong_field": 42}),
            "latency_ms": 100,
        }
        result = validator.validate(routed_task["task_id"], output, execution_db)
        assert result.schema_valid is False

    def test_timeout_detected(self, validator, routed_task, execution_db):
        """Timeout is detected when latency exceeds node timeout."""
        output = {
            "output_data": json.dumps({
                "task_id": routed_task["task_id"],
                "result": "late-result",
                "status": "success",
                "metrics": {"accuracy": 0.9, "completeness": 0.9},
            }),
            "latency_ms": 999999,  # Way over the 60000ms timeout
        }
        result = validator.validate(routed_task["task_id"], output, execution_db)
        assert result.timeout_valid is False

    def test_quality_below_threshold(self, validator, routed_task, execution_db):
        """Quality below threshold is detected for anomalous metrics."""
        output = {
            "output_data": json.dumps({
                "task_id": routed_task["task_id"],
                "result": "bad-quality",
                "status": "success",
                "metrics": {"accuracy": -5.0, "completeness": -5.0},
            }),
            "latency_ms": 100,
        }
        result = validator.validate(routed_task["task_id"], output, execution_db)
        assert result.quality_score < OutputValidator.QUALITY_THRESHOLD

    def test_guardian_alert_emitted(self, validator, routed_task, execution_db):
        """Guardian alert is written to DB when validation fails."""
        output = {
            "output_data": json.dumps({"bad": True}),
            "latency_ms": 100,
        }
        result = validator.validate(routed_task["task_id"], output, execution_db)
        assert result.guardian_alert is not None

        # Verify alert exists in DB
        conn = sqlite3.connect(str(execution_db))
        conn.execute("PRAGMA foreign_keys = ON")
        conn.row_factory = sqlite3.Row
        alert = conn.execute(
            "SELECT * FROM guardian_alert WHERE alert_id = ?",
            (result.guardian_alert,),
        ).fetchone()
        conn.close()

        assert alert is not None
        assert alert["task_id"] == routed_task["task_id"]
        assert alert["severity"] in ("CRITICAL", "WARNING")
