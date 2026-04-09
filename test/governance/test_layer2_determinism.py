"""P7 — Layer 2 determinism tests: L1 deterministic, L2 may vary."""
from __future__ import annotations

import pytest

from oasis.governance.clerks.llm_interface import MockLLM
from oasis.governance.clerks.registrar import Registrar
from oasis.governance.clerks.speaker import Speaker
from oasis.governance.messages import IdentityAttestation


class TestLayer1Deterministic:
    """Same input to Layer 1 always produces the same output."""

    def test_same_input_same_output(self, governance_db):
        registrar = Registrar(
            governance_db, "did:mock:clerk-registrar", llm_enabled=False,
        )
        registrar.open_session("sess-determ", 0.1)

        attestation = IdentityAttestation(
            session_id="sess-determ",
            agent_did="did:mock:producer-1",
            agent_type="producer",
            signature="valid-sig",
            reputation_score=0.5,
        )

        result1 = registrar.layer1_process(attestation)

        # Clean up so we can run the exact same input again
        import sqlite3
        conn = sqlite3.connect(str(governance_db))
        conn.execute(
            "DELETE FROM message_log WHERE sender_did = 'did:mock:producer-1' "
            "AND msg_type = 'IDENTITY_ATTESTATION'"
        )
        conn.commit()
        conn.close()

        result2 = registrar.layer1_process(attestation)

        assert result1["passed"] == result2["passed"]
        assert result1["errors"] == result2["errors"]
        assert result1["result"]["agent_did"] == result2["result"]["agent_did"]


class TestLayer2MayVary:
    """Layer 2 results may vary — non-deterministic is acceptable."""

    def test_layer2_nondeterministic_ok(self, governance_db):
        # Two different MockLLM instances returning different responses
        llm1 = MockLLM(default_response="Analysis version A.")
        llm2 = MockLLM(default_response="Analysis version B — different perspective.")

        speaker1 = Speaker(
            governance_db, "did:mock:clerk-speaker",
            llm_enabled=True, llm=llm1,
        )
        speaker2 = Speaker(
            governance_db, "did:mock:clerk-speaker",
            llm_enabled=True, llm=llm2,
        )

        ctx = {
            "session_id": "sess-determ",
            "round_num": 1,
            "messages": [
                {"agent_did": "did:mock:p1", "content": "I support", "position": "approve"},
            ],
            "participant_dids": ["did:mock:p1"],
        }

        result1 = speaker1.layer2_reason(ctx)
        result2 = speaker2.layer2_reason(ctx)

        # Both return valid results, but summaries may differ
        assert result1 is not None
        assert result2 is not None
        assert result1["summary"] != result2["summary"]
        # Structure is the same
        assert set(result1.keys()) == set(result2.keys())


class TestCombinedResultDocumented:
    """Combined L1+L2 result is properly structured and documented."""

    def test_combined_result(self, governance_db):
        llm = MockLLM(default_response="Advisory assessment.")
        registrar = Registrar(
            governance_db, "did:mock:clerk-registrar",
            llm_enabled=True, llm=llm,
        )
        registrar.open_session("sess-combined", 0.1)

        attestation = IdentityAttestation(
            session_id="sess-combined",
            agent_did="did:mock:producer-1",
            agent_type="producer",
            signature="valid-sig",
            reputation_score=0.5,
        )

        l1 = registrar.layer1_process(attestation)
        l2 = registrar.layer2_reason({
            "session_id": "sess-combined",
            "agent_did": "did:mock:producer-1",
            "recent_registrations": [
                {"agent_did": "did:mock:producer-1", "timestamp": "2026-01-01T00:00:00Z",
                 "display_name": "Producer 1"}
            ],
        })

        combined = {
            "decision": l1["passed"],
            "layer1_result": l1,
            "layer2_advisory": l2,
            "layer2_is_advisory_only": True,
        }

        # Document the combined structure
        assert "decision" in combined
        assert "layer1_result" in combined
        assert "layer2_advisory" in combined
        assert combined["layer2_is_advisory_only"] is True
        assert isinstance(combined["decision"], bool)
        assert isinstance(combined["layer2_advisory"], dict)
