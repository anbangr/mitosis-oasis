"""P7 — Regulator bid feasibility assessment tests."""
from __future__ import annotations

import pytest

from oasis.governance.clerks.llm_interface import MockLLM
from oasis.governance.clerks.regulator import Regulator


class TestFeasibleBid:
    """Reasonable bids pass feasibility assessment."""

    def test_feasible_bid_passes(self, governance_db):
        llm = MockLLM(default_response="All bids appear feasible.")
        regulator = Regulator(
            governance_db, "did:mock:clerk-regulator",
            llm_enabled=True, llm=llm,
        )
        result = regulator.layer2_reason({
            "session_id": "sess-1",
            "bid_set": [
                {
                    "bidder_did": "did:mock:producer-1",
                    "stake_amount": 0.5,
                    "estimated_latency_ms": 30_000,
                    "task_node_id": "task-a",
                },
                {
                    "bidder_did": "did:mock:producer-2",
                    "stake_amount": 0.6,
                    "estimated_latency_ms": 25_000,
                    "task_node_id": "task-b",
                },
            ],
            "bidder_histories": {},
            "fairness_score": 0.8,
        })
        assert result is not None
        assert result["feasibility_concerns"] == []
        assert result["collusion_detected"] is False


class TestInfeasibleBid:
    """Unreasonable bids get flagged."""

    def test_infeasible_flagged(self, governance_db):
        llm = MockLLM(default_response="Latency concern noted.")
        regulator = Regulator(
            governance_db, "did:mock:clerk-regulator",
            llm_enabled=True, llm=llm,
        )
        result = regulator.layer2_reason({
            "session_id": "sess-1",
            "bid_set": [
                {
                    "bidder_did": "did:mock:producer-1",
                    "stake_amount": 0.01,  # below MIN_REASONABLE_STAKE
                    "estimated_latency_ms": 500_000,  # above MAX_REASONABLE_LATENCY_MS
                    "task_node_id": "task-a",
                },
            ],
            "bidder_histories": {
                "did:mock:producer-1": {"failure_rate": 0.8},
            },
            "fairness_score": 0.3,
        })
        assert result is not None
        assert len(result["feasibility_concerns"]) >= 2  # latency + stake + failure rate
        assert any("latency" in c.lower() for c in result["feasibility_concerns"])
        assert any("stake" in c.lower() for c in result["feasibility_concerns"])


class TestCoordinatedPattern:
    """Coordinated bidding patterns are detected."""

    def test_coordinated_pattern_detected(self, governance_db):
        llm = MockLLM(default_response="No additional concerns.")
        regulator = Regulator(
            governance_db, "did:mock:clerk-regulator",
            llm_enabled=True, llm=llm,
        )
        # Two different bidders with identical stakes on the same node
        result = regulator.layer2_reason({
            "session_id": "sess-1",
            "bid_set": [
                {
                    "bidder_did": "did:mock:producer-1",
                    "stake_amount": 0.5,
                    "estimated_latency_ms": 30_000,
                    "task_node_id": "task-a",
                },
                {
                    "bidder_did": "did:mock:producer-2",
                    "stake_amount": 0.5,
                    "estimated_latency_ms": 30_000,
                    "task_node_id": "task-a",
                },
            ],
            "bidder_histories": {},
            "fairness_score": 0.8,
        })
        assert result is not None
        assert result["collusion_detected"] is True
        assert any("identical" in f.lower() or "stakes" in f.lower()
                    for f in result["compliance_flags"])
