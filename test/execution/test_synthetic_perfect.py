"""Tests for SyntheticGenerator in 'perfect' quality mode."""
from __future__ import annotations

import json

import pytest

from oasis.config import PlatformConfig
from oasis.execution.synthetic import SyntheticGenerator


@pytest.fixture()
def generator() -> SyntheticGenerator:
    config = PlatformConfig(
        synthetic_quality="perfect",
        synthetic_latency_ms=(50, 200),
    )
    return SyntheticGenerator(config)


@pytest.fixture()
def sample_task() -> dict:
    return {
        "task_id": "task-perfect-001",
        "session_id": "sess-001",
        "node_id": "node-001",
        "agent_did": "did:test:agent-1",
        "status": "committed",
    }


class TestSyntheticPerfect:
    def test_all_outputs_valid(self, generator, sample_task):
        """All outputs from perfect mode have success=True."""
        for _ in range(20):
            output = generator.generate_output(sample_task)
            assert output.success is True

    def test_schema_correct(self, generator, sample_task):
        """Perfect outputs contain expected fields: task_id, result, status."""
        output = generator.generate_output(sample_task)
        data = json.loads(output.output_data)
        assert "task_id" in data
        assert "result" in data
        assert "status" in data
        assert data["status"] == "success"

    def test_within_timeout(self, generator, sample_task):
        """Perfect outputs have latency within configured range."""
        for _ in range(20):
            output = generator.generate_output(sample_task)
            assert 50 <= output.latency_ms <= 200
