"""Synthetic output generator for testing execution without real LLM agents."""
from __future__ import annotations

import json
import random
import uuid
from dataclasses import dataclass, field
from typing import Any

from oasis.config import PlatformConfig


@dataclass
class SyntheticOutput:
    """Result produced by the synthetic generator."""

    task_id: str
    output_data: str  # JSON-encoded string
    latency_ms: int
    success: bool
    failure_reason: str | None = None


class SyntheticGenerator:
    """Generate synthetic task outputs for testing without real LLM agents.

    Supports three quality profiles:
    - **perfect**: all outputs are valid, correct schema, within timeout
    - **mixed**: configurable success rate with varied failure modes
    - **adversarial**: high failure rate with malicious output patterns
    """

    def __init__(self, config: PlatformConfig) -> None:
        self.config = config

    def generate_output(self, task_assignment: dict) -> SyntheticOutput:
        """Generate a synthetic output for the given task assignment.

        Delegates to the appropriate quality profile based on config.
        """
        quality = self.config.synthetic_quality
        if quality == "perfect":
            return self._perfect_output(task_assignment)
        elif quality == "mixed":
            return self._mixed_output(
                task_assignment, self.config.synthetic_success_rate
            )
        else:  # adversarial
            return self._adversarial_output(task_assignment)

    def _perfect_output(self, task: dict) -> SyntheticOutput:
        """Generate a valid output: correct schema, correct data, within timeout."""
        latency = random.randint(*self.config.synthetic_latency_ms)
        output_data = {
            "task_id": task["task_id"],
            "result": f"synthetic-result-{task['task_id']}",
            "status": "success",
            "metrics": {"accuracy": 0.95, "completeness": 1.0},
        }
        return SyntheticOutput(
            task_id=task["task_id"],
            output_data=json.dumps(output_data),
            latency_ms=latency,
            success=True,
        )

    def _mixed_output(
        self, task: dict, success_rate: float
    ) -> SyntheticOutput:
        """Generate output with configurable failure modes.

        With probability ``success_rate`` produces a valid output; otherwise
        picks a random failure mode: timeout, schema_mismatch, or partial_output.
        """
        if random.random() < success_rate:
            return self._perfect_output(task)

        failure_mode = random.choice(["timeout", "schema_mismatch", "partial_output"])
        return self._make_failure(task, failure_mode)

    def _adversarial_output(self, task: dict) -> SyntheticOutput:
        """Generate adversarial outputs: high failure rate, malicious patterns."""
        # 80% chance of failure
        if random.random() < 0.8:
            failure_mode = random.choice([
                "timeout",
                "schema_mismatch",
                "malicious_payload",
                "inflated_metrics",
                "contradictory_data",
            ])
            return self._make_failure(task, failure_mode)

        # Even "successful" adversarial outputs have inflated metrics
        latency = random.randint(*self.config.synthetic_latency_ms)
        output_data = {
            "task_id": task["task_id"],
            "result": f"adversarial-result-{task['task_id']}",
            "status": "success",
            "metrics": {"accuracy": 1.0, "completeness": 1.0},
        }
        return SyntheticOutput(
            task_id=task["task_id"],
            output_data=json.dumps(output_data),
            latency_ms=latency,
            success=True,
        )

    def _make_failure(self, task: dict, mode: str) -> SyntheticOutput:
        """Create a failed output for the given failure mode."""
        task_id = task["task_id"]
        lo, hi = self.config.synthetic_latency_ms

        if mode == "timeout":
            # Latency exceeds expected timeout by a large margin
            latency = hi * 10
            output_data = json.dumps({
                "task_id": task_id,
                "result": None,
                "status": "timeout",
            })
            return SyntheticOutput(
                task_id=task_id,
                output_data=output_data,
                latency_ms=latency,
                success=False,
                failure_reason="timeout",
            )

        if mode == "schema_mismatch":
            latency = random.randint(lo, hi)
            # Wrong schema: missing required fields, wrong types
            output_data = json.dumps({
                "wrong_field": 42,
                "unexpected": True,
            })
            return SyntheticOutput(
                task_id=task_id,
                output_data=output_data,
                latency_ms=latency,
                success=False,
                failure_reason="schema_mismatch",
            )

        if mode == "partial_output":
            latency = random.randint(lo, hi)
            output_data = json.dumps({
                "task_id": task_id,
                "result": None,
                "status": "partial",
                "metrics": {},
            })
            return SyntheticOutput(
                task_id=task_id,
                output_data=output_data,
                latency_ms=latency,
                success=False,
                failure_reason="partial_output",
            )

        if mode == "malicious_payload":
            latency = random.randint(lo, hi)
            output_data = json.dumps({
                "task_id": task_id,
                "result": "<script>alert('xss')</script>",
                "status": "success",
                "metrics": {"accuracy": -999, "completeness": -999},
                "__admin__": True,
            })
            return SyntheticOutput(
                task_id=task_id,
                output_data=output_data,
                latency_ms=latency,
                success=False,
                failure_reason="malicious_payload",
            )

        if mode == "inflated_metrics":
            latency = random.randint(lo, hi)
            output_data = json.dumps({
                "task_id": task_id,
                "result": f"inflated-{task_id}",
                "status": "success",
                "metrics": {"accuracy": 999.99, "completeness": 999.99},
            })
            return SyntheticOutput(
                task_id=task_id,
                output_data=output_data,
                latency_ms=latency,
                success=False,
                failure_reason="inflated_metrics",
            )

        if mode == "contradictory_data":
            latency = random.randint(lo, hi)
            output_data = json.dumps({
                "task_id": task_id,
                "result": f"contradictory-{task_id}",
                "status": "failed",
                "metrics": {"accuracy": 1.0, "completeness": 1.0},
            })
            return SyntheticOutput(
                task_id=task_id,
                output_data=output_data,
                latency_ms=latency,
                success=False,
                failure_reason="contradictory_data",
            )

        # Fallback
        return SyntheticOutput(
            task_id=task_id,
            output_data=json.dumps({"error": "unknown failure"}),
            latency_ms=random.randint(lo, hi),
            success=False,
            failure_reason=mode,
        )
