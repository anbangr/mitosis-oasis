"""P7 — Speaker deliberation summarization tests."""
from __future__ import annotations

import pytest

from oasis.governance.clerks.llm_interface import MockLLM
from oasis.governance.clerks.speaker import Speaker


def _make_messages(positions: list[str]) -> list[dict]:
    """Create deliberation messages from a list of positions."""
    return [
        {
            "agent_did": f"did:mock:producer-{i}",
            "content": f"I argue for position: {pos}",
            "position": pos,
        }
        for i, pos in enumerate(positions)
    ]


class TestSummaryGeneration:
    """Layer 2 generates a summary of deliberation."""

    def test_summary_generated(self, governance_db):
        llm = MockLLM(default_response="Round summary: participants discussed approach A vs B.")
        speaker = Speaker(
            governance_db, "did:mock:clerk-speaker",
            llm_enabled=True, llm=llm,
        )
        messages = _make_messages(["approve", "approve", "reject", "approve"])
        result = speaker.layer2_reason({
            "session_id": "sess-1",
            "round_num": 1,
            "messages": messages,
            "participant_dids": [f"did:mock:producer-{i}" for i in range(4)],
        })
        assert result is not None
        assert isinstance(result["summary"], str)
        assert len(result["summary"]) > 0
        assert "convergence" in result
        assert isinstance(result["convergence"], float)


class TestMinorityPreservation:
    """Minority positions are identified and preserved."""

    def test_minority_positions_preserved(self, governance_db):
        llm = MockLLM(default_response="Summary with minority noted.")
        speaker = Speaker(
            governance_db, "did:mock:clerk-speaker",
            llm_enabled=True, llm=llm,
        )
        # 8 approve, 1 reject, 1 abstain — reject and abstain are minorities
        positions = ["approve"] * 8 + ["reject"] + ["abstain"]
        messages = _make_messages(positions)
        result = speaker.layer2_reason({
            "session_id": "sess-1",
            "round_num": 1,
            "messages": messages,
            "participant_dids": [f"did:mock:producer-{i}" for i in range(10)],
        })
        assert result is not None
        assert isinstance(result["minority_positions"], list)
        assert "reject" in result["minority_positions"] or "abstain" in result["minority_positions"]


class TestConvergenceDetection:
    """High agreement fraction triggers convergence."""

    def test_convergence_detected(self, governance_db):
        llm = MockLLM(default_response="Strong convergence toward approval.")
        speaker = Speaker(
            governance_db, "did:mock:clerk-speaker",
            llm_enabled=True, llm=llm,
        )
        # 9 out of 10 agree — convergence > 0.75
        positions = ["approve"] * 9 + ["reject"]
        messages = _make_messages(positions)
        result = speaker.layer2_reason({
            "session_id": "sess-1",
            "round_num": 2,
            "messages": messages,
            "participant_dids": [f"did:mock:producer-{i}" for i in range(10)],
        })
        assert result is not None
        assert result["convergence"] >= 0.75


class TestDeadlockDetection:
    """Repeated identical position distribution signals deadlock."""

    def test_deadlock_detected(self, governance_db):
        llm = MockLLM(default_response="Deadlock persists after multiple rounds.")
        speaker = Speaker(
            governance_db, "did:mock:clerk-speaker",
            llm_enabled=True, llm=llm,
        )
        positions = ["approve", "approve", "reject", "reject"]
        messages = _make_messages(positions)
        frozen_counts = {"approve": 2, "reject": 2}
        result = speaker.layer2_reason({
            "session_id": "sess-1",
            "round_num": 3,
            "messages": messages,
            "participant_dids": [f"did:mock:producer-{i}" for i in range(4)],
            "previous_rounds": [
                {"position_counts": frozen_counts},
                {"position_counts": frozen_counts},
            ],
        })
        assert result is not None
        assert result["deadlock_detected"] is True
