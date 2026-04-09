"""Tests for SyntheticGenerator in 'mixed' quality mode."""
from __future__ import annotations

import json

import pytest

from oasis.config import PlatformConfig
from oasis.execution.synthetic import SyntheticGenerator


@pytest.fixture()
def generator() -> SyntheticGenerator:
    config = PlatformConfig(
        synthetic_quality="mixed",
        synthetic_success_rate=0.8,
        synthetic_latency_ms=(50, 200),
    )
    return SyntheticGenerator(config)


@pytest.fixture()
def sample_task() -> dict:
    return {
        "task_id": "task-mixed-001",
        "session_id": "sess-001",
        "node_id": "node-001",
        "agent_did": "did:test:agent-1",
        "status": "committed",
    }


class TestSyntheticMixed:
    def test_approximate_success_rate(self, generator, sample_task):
        """~80% success rate (statistical test with tolerance)."""
        n = 500
        successes = sum(
            1 for _ in range(n)
            if generator.generate_output(sample_task).success
        )
        rate = successes / n
        # Allow generous tolerance for randomness
        assert 0.60 < rate < 0.95, f"Success rate {rate:.2f} outside expected range"

    def test_failure_modes_varied(self, generator, sample_task):
        """Multiple failure modes are produced (not all the same type)."""
        failure_reasons = set()
        for _ in range(200):
            output = generator.generate_output(sample_task)
            if not output.success and output.failure_reason:
                failure_reasons.add(output.failure_reason)
        # Should see at least 2 different failure modes
        assert len(failure_reasons) >= 2, f"Only saw: {failure_reasons}"

    def test_schema_mismatches_present(self, generator, sample_task):
        """Some outputs have schema mismatches."""
        has_schema_mismatch = False
        for _ in range(200):
            output = generator.generate_output(sample_task)
            if output.failure_reason == "schema_mismatch":
                has_schema_mismatch = True
                data = json.loads(output.output_data)
                # Schema-mismatched output should lack expected fields
                assert "task_id" not in data or "result" not in data
                break
        assert has_schema_mismatch, "No schema_mismatch failures produced"

    def test_timeouts_present(self, generator, sample_task):
        """Some outputs have timeout failures."""
        has_timeout = False
        for _ in range(200):
            output = generator.generate_output(sample_task)
            if output.failure_reason == "timeout":
                has_timeout = True
                assert output.latency_ms > 200  # Exceeds max latency
                break
        assert has_timeout, "No timeout failures produced"
