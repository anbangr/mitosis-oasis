"""P7 — Layer 2 advisory-only tests: Layer 2 flags don't override Layer 1 decisions."""
from __future__ import annotations

import pytest

from oasis.governance.clerks.llm_interface import MockLLM
from oasis.governance.clerks.registrar import Registrar
from oasis.governance.clerks.regulator import Regulator
from oasis.governance.messages import IdentityAttestation, TaskBid


class TestLayer2DoesNotOverrideLayer1Pass:
    """Layer 2 flags (even severe) don't change a Layer 1 pass to a fail."""

    def test_layer2_flags_dont_override_pass(self, governance_db):
        llm = MockLLM(responses={"sybil": "CRITICAL Sybil attack detected!"})
        registrar = Registrar(
            governance_db, "did:mock:clerk-registrar",
            llm_enabled=True, llm=llm,
        )

        # Open session
        registrar.open_session("sess-advisory", 0.1)

        # Valid attestation — Layer 1 should pass
        attestation = IdentityAttestation(
            session_id="sess-advisory",
            agent_did="did:mock:producer-1",
            agent_type="producer",
            signature="valid-sig",
            reputation_score=0.5,
        )
        l1_result = registrar.layer1_process(attestation)
        assert l1_result["passed"] is True

        # Layer 2 flags Sybil — but it's advisory only
        l2_result = registrar.layer2_reason({
            "session_id": "sess-advisory",
            "agent_did": "did:mock:producer-1",
            "recent_registrations": [
                {"agent_did": f"did:mock:agent-{i}", "timestamp": "2026-01-01T00:00:00Z",
                 "display_name": f"Agent {i}"}
                for i in range(10)
            ],
            "burst_threshold": 5,
            "burst_window_seconds": 60,
        })
        assert l2_result is not None
        assert l2_result["flagged"] is True

        # Layer 1 result is unchanged — still passed
        assert l1_result["passed"] is True


class TestLayer2DoesNotOverrideLayer1Fail:
    """Layer 2 'all clear' doesn't change a Layer 1 fail to a pass."""

    def test_layer2_clear_doesnt_override_fail(self, governance_db):
        llm = MockLLM(default_response="No issues detected.")
        registrar = Registrar(
            governance_db, "did:mock:clerk-registrar",
            llm_enabled=True, llm=llm,
        )
        registrar.open_session("sess-advisory-2", 0.5)

        # Invalid attestation — bad DID format → Layer 1 fails
        attestation = IdentityAttestation(
            session_id="sess-advisory-2",
            agent_did="invalid-no-did-prefix",
            agent_type="producer",
            signature="valid-sig",
            reputation_score=0.5,
        )
        l1_result = registrar.layer1_process(attestation)
        assert l1_result["passed"] is False

        # Layer 2 says all clear — but Layer 1 still failed
        l2_result = registrar.layer2_reason({
            "session_id": "sess-advisory-2",
            "agent_did": "invalid-no-did-prefix",
            "recent_registrations": [],
        })
        assert l2_result is not None
        assert l2_result["flagged"] is False

        # Layer 1 result is unchanged — still failed
        assert l1_result["passed"] is False


class TestAdvisoryAttachedToDecision:
    """Layer 2 advisory can be attached alongside Layer 1 decision."""

    def test_advisory_attached(self, governance_db):
        llm = MockLLM(default_response="Advisory: all clear.")
        registrar = Registrar(
            governance_db, "did:mock:clerk-registrar",
            llm_enabled=True, llm=llm,
        )
        registrar.open_session("sess-advisory-3", 0.1)

        attestation = IdentityAttestation(
            session_id="sess-advisory-3",
            agent_did="did:mock:producer-1",
            agent_type="producer",
            signature="valid-sig",
            reputation_score=0.5,
        )
        l1_result = registrar.layer1_process(attestation)
        l2_result = registrar.layer2_reason({
            "session_id": "sess-advisory-3",
            "agent_did": "did:mock:producer-1",
            "recent_registrations": [
                {"agent_did": "did:mock:producer-1", "timestamp": "2026-01-01T00:00:00Z",
                 "display_name": "Producer 1"}
            ],
        })

        # Both results can coexist — combined decision
        combined = {
            "layer1": l1_result,
            "layer2_advisory": l2_result,
        }
        assert combined["layer1"]["passed"] is True
        assert combined["layer2_advisory"] is not None
        assert "flagged" in combined["layer2_advisory"]
