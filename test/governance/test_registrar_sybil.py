"""P7 — Registrar Sybil pattern detection tests."""
from __future__ import annotations

from datetime import datetime, timezone, timedelta

import pytest

from oasis.governance.clerks.llm_interface import MockLLM
from oasis.governance.clerks.registrar import Registrar


# Diverse names to avoid false similarity matches
_DIVERSE_NAMES = [
    "AlphaBot", "BravoEngine", "CharlieProcessor", "DeltaWorker",
    "EchoRunner", "FoxtrotService", "GolfAnalyzer", "HotelCollector",
    "IndiaTransformer", "JulietValidator", "KiloScheduler", "LimaRouter",
]


def _make_registrations(count: int, window_seconds: int = 30, similar_names: bool = False) -> list[dict]:
    """Create a list of registrations within a time window."""
    base = datetime(2026, 4, 1, 12, 0, 0, tzinfo=timezone.utc)
    return [
        {
            "agent_did": f"did:mock:agent-{i}",
            "timestamp": (base + timedelta(seconds=i * (window_seconds // max(count, 1)))).isoformat(),
            "display_name": f"SybilBot-{i}" if similar_names else _DIVERSE_NAMES[i % len(_DIVERSE_NAMES)],
        }
        for i in range(count)
    ]


class TestBurstDetection:
    """Burst registration flags suspicious patterns."""

    def test_burst_flags_suspicious(self, governance_db):
        llm = MockLLM(responses={"sybil": "High confidence Sybil pattern."})
        registrar = Registrar(
            governance_db, "did:mock:clerk-registrar",
            llm_enabled=True, llm=llm,
        )
        # 10 registrations in 30 seconds (threshold is 5)
        regs = _make_registrations(10, window_seconds=30, similar_names=True)
        result = registrar.layer2_reason({
            "session_id": "sess-1",
            "agent_did": "did:mock:agent-0",
            "recent_registrations": regs,
            "burst_threshold": 5,
            "burst_window_seconds": 30,
        })
        assert result is not None
        assert result["flagged"] is True
        assert "Burst registration" in result["reason"]
        assert result["confidence"] > 0

    def test_normal_registration_passes(self, governance_db):
        llm = MockLLM()
        registrar = Registrar(
            governance_db, "did:mock:clerk-registrar",
            llm_enabled=True, llm=llm,
        )
        # 3 registrations spread over 10 minutes — well below threshold
        regs = _make_registrations(3, window_seconds=600)
        result = registrar.layer2_reason({
            "session_id": "sess-1",
            "agent_did": "did:mock:agent-0",
            "recent_registrations": regs,
            "burst_threshold": 5,
            "burst_window_seconds": 60,
        })
        assert result is not None
        assert result["flagged"] is False
        assert result["confidence"] == 0.0

    def test_threshold_configurable(self, governance_db):
        llm = MockLLM(responses={"sybil": "Flagged."})
        registrar = Registrar(
            governance_db, "did:mock:clerk-registrar",
            llm_enabled=True, llm=llm,
        )
        # 3 registrations — flagged if threshold is 2, not if 5
        regs = _make_registrations(3, window_seconds=10)

        result_low = registrar.layer2_reason({
            "session_id": "sess-1",
            "agent_did": "did:mock:agent-0",
            "recent_registrations": regs,
            "burst_threshold": 2,
            "burst_window_seconds": 60,
        })
        assert result_low["flagged"] is True

        result_high = registrar.layer2_reason({
            "session_id": "sess-1",
            "agent_did": "did:mock:agent-0",
            "recent_registrations": regs,
            "burst_threshold": 10,
            "burst_window_seconds": 60,
        })
        assert result_high["flagged"] is False
