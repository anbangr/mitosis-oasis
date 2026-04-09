"""Layer 2 LLM advisory override panel tests (4 tests)."""
from __future__ import annotations

import pytest

from oasis.adjudication.override_panel import (
    DeterministicDecision,
    OverridePanel,
)
from oasis.config import PlatformConfig
from oasis.governance.clerks.llm_interface import MockLLM


class TestOverrideLayer2:
    """Layer 2: LLM advisory evaluation."""

    def test_llm_disabled_no_advisory(self, adjudication_db, agents, config):
        """When LLM is disabled, layer2_evaluate returns None."""
        panel = OverridePanel(config, adjudication_db, llm_enabled=False)
        layer1 = DeterministicDecision(
            action="NEEDS_REVIEW",
            reason="Borderline quality",
            severity="WARNING",
        )
        context = {"quality_score": 0.5, "agent_did": agents[0]["agent_did"]}
        advisory = panel.layer2_evaluate(context, layer1)
        assert advisory is None

    def test_llm_enabled_evaluates_borderline(self, adjudication_db, agents, config):
        """When LLM is enabled and layer1 is NEEDS_REVIEW, LLM is consulted."""
        mock_llm = MockLLM(
            responses={"borderline": "DISMISS — quality is marginal but acceptable"},
            default_response="DISMISS",
        )
        panel = OverridePanel(
            config, adjudication_db, llm_enabled=True, llm=mock_llm
        )
        layer1 = DeterministicDecision(
            action="NEEDS_REVIEW",
            reason="Borderline quality",
            severity="WARNING",
        )
        context = {"quality_score": 0.5, "agent_did": agents[0]["agent_did"]}
        advisory = panel.layer2_evaluate(context, layer1)
        assert advisory is not None
        assert "DISMISS" in advisory.recommendation
        assert len(mock_llm.call_log) == 1

    def test_advisory_does_not_override_freeze(self, adjudication_db, agents, config):
        """Layer 2 advisory is NOT produced for FREEZE decisions."""
        mock_llm = MockLLM(default_response="DISMISS")
        panel = OverridePanel(
            config, adjudication_db, llm_enabled=True, llm=mock_llm
        )
        layer1 = DeterministicDecision(
            action="FREEZE",
            reason="Quality below threshold",
            severity="CRITICAL",
        )
        context = {"quality_score": 0.2, "agent_did": agents[0]["agent_did"]}
        advisory = panel.layer2_evaluate(context, layer1)
        assert advisory is None
        assert len(mock_llm.call_log) == 0  # LLM was not called

    def test_advisory_attached_to_decision(self, adjudication_db, agents):
        """Full decide() path: LLM advisory attached to AdjudicationDecision."""
        cfg = PlatformConfig(freeze_threshold=0.3, warn_threshold=0.7)
        mock_llm = MockLLM(default_response="ESCALATE — needs human review")
        panel = OverridePanel(cfg, adjudication_db, llm_enabled=True, llm=mock_llm)

        alert = {
            "type": "alert",
            "agent_did": agents[0]["agent_did"],
            "quality_score": 0.5,  # ≥ freeze(0.3) but < warn(0.7)
            "severity": "WARNING",
        }
        decision = panel.decide(alert)

        assert decision.decision_type == "needs_review"
        assert decision.layer2_advisory is not None
        assert "ESCALATE" in decision.layer2_advisory
