"""Platform configuration for the Mitosis-OASIS execution engine."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Tuple


@dataclass
class PlatformConfig:
    """Configuration for the OASIS execution platform.

    Controls execution mode (LLM vs synthetic), synthetic behaviour
    parameters, adjudication settings, constitutional thresholds,
    and fee/reputation parameters.
    """

    # Execution mode
    execution_mode: Literal["llm", "synthetic"] = "synthetic"

    # Synthetic execution parameters
    synthetic_quality: Literal["perfect", "mixed", "adversarial"] = "mixed"
    synthetic_success_rate: float = 0.8
    synthetic_latency_ms: Tuple[int, int] = (50, 200)

    # Adjudication
    adjudication_llm_enabled: bool = False

    # Constitutional thresholds
    freeze_threshold: float = 0.9
    warn_threshold: float = 0.7
    coordination_threshold: float = 0.7
    sanction_floor: float = 0.1

    # Fee parameters
    protocol_fee_rate: float = 0.02
    insurance_fee_rate: float = 0.01

    # Reputation parameters
    reputation_alpha: float = 0.5
    reputation_neutral: float = 0.5

    def __post_init__(self) -> None:
        if self.execution_mode not in ("llm", "synthetic"):
            raise ValueError(
                f"Invalid execution_mode: {self.execution_mode!r}; "
                "must be 'llm' or 'synthetic'"
            )
        if self.synthetic_quality not in ("perfect", "mixed", "adversarial"):
            raise ValueError(
                f"Invalid synthetic_quality: {self.synthetic_quality!r}; "
                "must be 'perfect', 'mixed', or 'adversarial'"
            )
        if not (0.0 <= self.synthetic_success_rate <= 1.0):
            raise ValueError("synthetic_success_rate must be between 0 and 1")
        if self.synthetic_latency_ms[0] > self.synthetic_latency_ms[1]:
            raise ValueError(
                "synthetic_latency_ms[0] must be <= synthetic_latency_ms[1]"
            )
