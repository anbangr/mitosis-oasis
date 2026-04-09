"""Tests for SyntheticGenerator in 'adversarial' quality mode."""
from __future__ import annotations

import json

import pytest

from oasis.config import PlatformConfig
from oasis.execution.synthetic import SyntheticGenerator


@pytest.fixture()
def generator() -> SyntheticGenerator:
    config = PlatformConfig(
        synthetic_quality="adversarial",
        synthetic_latency_ms=(50, 200),
    )
    return SyntheticGenerator(config)


@pytest.fixture()
def sample_task() -> dict:
    return {
        "task_id": "task-adv-001",
        "session_id": "sess-001",
        "node_id": "node-001",
        "agent_did": "did:test:agent-1",
        "status": "committed",
    }


class TestSyntheticAdversarial:
    def test_high_failure_rate(self, generator, sample_task):
        """Adversarial mode has high failure rate (>50%)."""
        n = 500
        failures = sum(
            1 for _ in range(n)
            if not generator.generate_output(sample_task).success
        )
        rate = failures / n
        assert rate > 0.50, f"Failure rate {rate:.2f} too low for adversarial mode"

    def test_malicious_patterns(self, generator, sample_task):
        """Adversarial mode produces malicious output patterns."""
        malicious_reasons = {
            "malicious_payload",
            "inflated_metrics",
            "contradictory_data",
        }
        seen = set()
        for _ in range(500):
            output = generator.generate_output(sample_task)
            if output.failure_reason in malicious_reasons:
                seen.add(output.failure_reason)
        # Should see at least one malicious pattern type
        assert len(seen) >= 1, f"No malicious patterns seen, got: {seen}"

    def test_guardian_alerts_for_adversarial(self, generator, sample_task, execution_db, producers):
        """Adversarial outputs trigger guardian alerts when validated."""
        from oasis.execution.validator import OutputValidator
        from oasis.execution.router import route_tasks
        from .conftest import drive_to_deployed

        info = drive_to_deployed(execution_db, producers)
        tasks = route_tasks(info["session_id"], execution_db)
        assert len(tasks) > 0
        task = tasks[0]

        validator = OutputValidator()
        alert_count = 0
        for _ in range(50):
            output = generator.generate_output({"task_id": task["task_id"]})
            result = validator.validate(
                task["task_id"],
                {"output_data": output.output_data, "latency_ms": output.latency_ms},
                execution_db,
            )
            if result.guardian_alert is not None:
                alert_count += 1

        # Adversarial mode should trigger at least some alerts
        assert alert_count > 0, "No guardian alerts generated from adversarial outputs"
