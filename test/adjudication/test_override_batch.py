"""Override panel batch processing tests (2 tests)."""
from __future__ import annotations

import sqlite3

import pytest

from oasis.adjudication.override_panel import OverridePanel
from oasis.config import PlatformConfig


class TestOverrideBatch:
    """Batch processing of multiple alerts and flags."""

    def test_batch_processes_multiple(self, adjudication_db, agents, config):
        """process_batch handles multiple alerts and flags, returning decisions for each."""
        panel = OverridePanel(config, adjudication_db)

        alerts = [
            {
                "type": "alert",
                "agent_did": agents[0]["agent_did"],
                "quality_score": 0.3,
                "severity": "CRITICAL",
            }
            for i in range(3)
        ]
        flags = [
            {
                "type": "flag",
                "agent_did_1": agents[0]["agent_did"],
                "agent_did_2": agents[1]["agent_did"],
                "score": 0.85,
            }
            for i in range(2)
        ]

        decisions = panel.process_batch(alerts, flags)
        assert len(decisions) == 5
        # 3 alerts should be FREEZE, 2 flags should be FLAG_AND_DELAY
        alert_decisions = [d for d in decisions if d.decision_type == "freeze"]
        flag_decisions = [d for d in decisions if d.decision_type == "flag_and_delay"]
        assert len(alert_decisions) == 3
        assert len(flag_decisions) == 2

    def test_batch_decisions_stored_in_db(self, adjudication_db, agents, config):
        """Batch decisions are persisted to the adjudication_decision table."""
        panel = OverridePanel(config, adjudication_db)

        alerts = [
            {
                "type": "alert",
                "agent_did": agents[0]["agent_did"],
                "quality_score": 0.5,
                "severity": "WARNING",
            }
            for i in range(2)
        ]

        decisions = panel.process_batch(alerts, [])
        assert len(decisions) == 2

        # Verify stored in DB
        conn = sqlite3.connect(str(adjudication_db))
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT * FROM adjudication_decision WHERE decision_id IN (?, ?)",
            (decisions[0].decision_id, decisions[1].decision_id),
        ).fetchall()
        conn.close()
        assert len(rows) == 2
