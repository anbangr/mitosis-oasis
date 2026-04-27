"""Platform configuration for the Mitosis-OASIS execution engine."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Tuple

_VALID_GOVERNANCE_MODES = ("none", "emergent", "structural", "full")
_VALID_HITL_MODES = ("simulated", "disabled")


@dataclass
class PlatformConfig:
    """Configuration for the OASIS execution platform.

    Controls execution mode (LLM vs synthetic), governance mode, synthetic
    behaviour parameters, adjudication settings, constitutional thresholds,
    and fee/reputation parameters.
    """

    # Governance mode — which SoP branches are active
    # "none"       — no governance sessions (Baseline)
    # "emergent"   — prompt-based deliberation only, no contract enforcement
    # "structural" — Legislation + Execution branches (no Adjudication)
    # "full"       — all three branches + economic incentives
    governance_mode: Literal["none", "emergent", "structural", "full"] = "full"

    # Execution mode
    execution_mode: Literal["llm", "synthetic"] = "synthetic"

    # Synthetic execution parameters
    synthetic_quality: Literal["perfect", "mixed", "adversarial"] = "mixed"
    synthetic_success_rate: float = 0.8
    synthetic_latency_ms: Tuple[int, int] = (50, 200)

    # Adjudication branch controls (Gap 5)
    adjudication_enabled: bool = True
    adjudication_llm_enabled: bool = False
    hitl_mode: Literal["simulated", "disabled"] = "disabled"
    override_panel_size: int = 3
    decision_latency_rounds: int = 2
    coordination_detection_enabled: bool = True

    # Economic incentive controls (Gap 5)
    economic_incentives_enabled: bool = True
    foundation_principal_count: int = 0
    milestone_funding_tranches: int = 0

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

    # System scaling & modules
    max_agents: int = 1000
    active_modules: list[str] = field(default_factory=lambda: ["reputation", "treasury"])

    def __post_init__(self) -> None:
        if self.governance_mode not in _VALID_GOVERNANCE_MODES:
            raise ValueError(
                f"Invalid governance_mode: {self.governance_mode!r}; "
                f"must be one of {_VALID_GOVERNANCE_MODES}"
            )
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
        if self.hitl_mode not in _VALID_HITL_MODES:
            raise ValueError(
                f"Invalid hitl_mode: {self.hitl_mode!r}; "
                f"must be one of {_VALID_HITL_MODES}"
            )
        if self.override_panel_size < 1:
            raise ValueError("override_panel_size must be >= 1")
        if self.decision_latency_rounds < 0:
            raise ValueError("decision_latency_rounds must be >= 0")
