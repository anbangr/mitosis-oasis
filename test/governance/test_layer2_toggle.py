"""P7 — Layer 2 toggle tests: LLM disabled vs enabled."""
from __future__ import annotations

import pytest

from oasis.governance.clerks.llm_interface import MockLLM
from oasis.governance.clerks.registrar import Registrar
from oasis.governance.clerks.speaker import Speaker
from oasis.governance.clerks.regulator import Regulator
from oasis.governance.clerks.codifier import Codifier


class TestLLMDisabledReturnsNone:
    """When llm_enabled=False, layer2_reason() returns None for all clerks."""

    def test_all_clerks_return_none_when_disabled(self, governance_db):
        clerks = [
            Registrar(governance_db, "did:mock:clerk-registrar", llm_enabled=False),
            Speaker(governance_db, "did:mock:clerk-speaker", llm_enabled=False),
            Regulator(governance_db, "did:mock:clerk-regulator", llm_enabled=False),
            Codifier(governance_db, "did:mock:clerk-codifier", llm_enabled=False),
        ]
        for clerk in clerks:
            result = clerk.layer2_reason({"session_id": "s1"})
            assert result is None, f"{clerk.__class__.__name__} should return None"


class TestLLMEnabledReturnsAdvisory:
    """When llm_enabled=True with MockLLM, layer2_reason() returns advisory dict."""

    def test_all_clerks_return_dict_when_enabled(self, governance_db):
        llm = MockLLM(default_response="Advisory response.")
        clerks = [
            Registrar(governance_db, "did:mock:clerk-registrar", llm_enabled=True, llm=llm),
            Speaker(governance_db, "did:mock:clerk-speaker", llm_enabled=True, llm=llm),
            Regulator(governance_db, "did:mock:clerk-regulator", llm_enabled=True, llm=llm),
            Codifier(governance_db, "did:mock:clerk-codifier", llm_enabled=True, llm=llm),
        ]
        contexts = [
            {"session_id": "s1", "agent_did": "did:mock:agent-0", "recent_registrations": [
                {"agent_did": "did:mock:a1", "timestamp": "2026-01-01T00:00:00Z", "display_name": "A1"}
            ]},
            {"session_id": "s1", "round_num": 1, "messages": [
                {"agent_did": "did:mock:p1", "content": "I approve", "position": "approve"}
            ], "participant_dids": ["did:mock:p1"]},
            {"session_id": "s1", "bid_set": [
                {"bidder_did": "did:mock:p1", "stake_amount": 0.5, "estimated_latency_ms": 1000, "task_node_id": "t1"}
            ], "bidder_histories": {}, "fairness_score": 0.9},
            {"proposal_rationale": "Test", "spec": {}, "service_specs": []},
        ]
        for clerk, ctx in zip(clerks, contexts):
            result = clerk.layer2_reason(ctx)
            assert result is not None, f"{clerk.__class__.__name__} should return dict"
            assert isinstance(result, dict)


class TestLayer1UnaffectedByLayer2:
    """Layer 1 processing works the same regardless of LLM toggle."""

    def test_layer1_same_with_and_without_llm(self, governance_db):
        from oasis.governance.messages import IdentityAttestation, log_message, IdentityVerificationRequest

        # Open a session first
        registrar_no_llm = Registrar(
            governance_db, "did:mock:clerk-registrar", llm_enabled=False,
        )
        registrar_no_llm.open_session("sess-toggle", 0.1)

        llm = MockLLM()
        registrar_with_llm = Registrar(
            governance_db, "did:mock:clerk-registrar", llm_enabled=True, llm=llm,
        )

        attestation = IdentityAttestation(
            session_id="sess-toggle",
            agent_did="did:mock:producer-1",
            agent_type="producer",
            signature="valid-sig",
            reputation_score=0.5,
        )

        result_no_llm = registrar_no_llm.layer1_process(attestation)
        # Clear the message log entry so the second call doesn't hit duplicate
        import sqlite3
        conn = sqlite3.connect(str(governance_db))
        conn.execute("DELETE FROM message_log WHERE sender_did = 'did:mock:producer-1' AND msg_type = 'IDENTITY_ATTESTATION'")
        conn.commit()
        conn.close()

        result_with_llm = registrar_with_llm.layer1_process(attestation)

        assert result_no_llm["passed"] == result_with_llm["passed"]
        assert result_no_llm["errors"] == result_with_llm["errors"]
