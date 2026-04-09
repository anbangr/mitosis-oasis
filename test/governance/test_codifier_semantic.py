"""P7 — Codifier semantic consistency validation tests."""
from __future__ import annotations

import pytest

from oasis.governance.clerks.llm_interface import MockLLM
from oasis.governance.clerks.codifier import Codifier


class TestConsistentSpec:
    """Semantically consistent spec passes."""

    def test_consistent_spec_passes(self, governance_db):
        llm = MockLLM(default_response="Spec is consistent with proposal intent.")
        codifier = Codifier(
            governance_db, "did:mock:clerk-codifier",
            llm_enabled=True, llm=llm,
        )
        result = codifier.layer2_reason({
            "proposal_rationale": "Collect and analyze data from multiple sources.",
            "spec": {
                "collaboration_contract_spec": {
                    "total_budget": 600.0,
                    "deadline_ms": 300_000,
                },
            },
            "service_specs": [
                {"service_id": "collector", "token_budget": 200.0},
                {"service_id": "analyzer", "token_budget": 300.0},
            ],
        })
        assert result is not None
        assert result["semantically_consistent"] is True
        assert result["issues"] == []


class TestSemanticMismatch:
    """Semantic mismatch between rationale and spec is flagged."""

    def test_semantic_mismatch_flagged(self, governance_db):
        llm = MockLLM(
            responses={"semantic": "Mismatch: rationale mentions transformation but no transform service."}
        )
        codifier = Codifier(
            governance_db, "did:mock:clerk-codifier",
            llm_enabled=True, llm=llm,
        )
        result = codifier.layer2_reason({
            "proposal_rationale": "Transform and validate all incoming datasets.",
            "spec": {
                "collaboration_contract_spec": {
                    "total_budget": 100.0,
                    "deadline_ms": 60_000,
                },
            },
            "service_specs": [
                {"service_id": "logger", "token_budget": 100.0},
            ],
        })
        assert result is not None
        assert result["semantically_consistent"] is False
        assert len(result["issues"]) > 0


class TestAmbiguousProposal:
    """Ambiguous or empty proposals are handled gracefully."""

    def test_empty_rationale_handled(self, governance_db):
        llm = MockLLM(default_response="Cannot assess — rationale is empty.")
        codifier = Codifier(
            governance_db, "did:mock:clerk-codifier",
            llm_enabled=True, llm=llm,
        )
        result = codifier.layer2_reason({
            "proposal_rationale": "",
            "spec": {},
            "service_specs": [],
        })
        assert result is not None
        assert result["semantically_consistent"] is False
        assert any("empty" in i.lower() or "no service" in i.lower()
                    for i in result["issues"])
