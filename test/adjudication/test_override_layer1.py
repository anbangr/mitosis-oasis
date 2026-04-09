"""Layer 1 deterministic override panel tests (5 tests)."""
from __future__ import annotations

import sqlite3

import pytest

from oasis.adjudication.override_panel import OverridePanel
from oasis.config import PlatformConfig


class TestOverrideLayer1:
    """Layer 1: deterministic rule evaluation."""

    def test_critical_alert_freeze(self, adjudication_db, agents, config):
        """Guardian alert with quality below freeze_threshold → FREEZE."""
        panel = OverridePanel(config, adjudication_db)
        alert = {
            "type": "alert",
            "alert_id": "alert-001",
            "agent_did": agents[0]["agent_did"],
            "quality_score": 0.3,  # well below freeze_threshold (0.9)
            "severity": "CRITICAL",
        }
        decision = panel.layer1_evaluate(alert)
        assert decision.action == "FREEZE"
        assert decision.severity == "CRITICAL"

    def test_borderline_needs_review(self, adjudication_db, agents, config):
        """Quality between freeze_threshold and warn_threshold → NEEDS_REVIEW."""
        # freeze_threshold=0.9, warn_threshold=0.7 by default
        # quality between these should not apply; let's adjust:
        # Actually: quality < freeze (0.9) → FREEZE, quality >= freeze but < warn...
        # Wait — the plan says:
        #   quality < freeze_threshold → FREEZE
        #   quality ≥ freeze_threshold but < warn_threshold → NEEDS_REVIEW
        # So freeze_threshold < warn_threshold. Let's configure accordingly.
        cfg = PlatformConfig(freeze_threshold=0.3, warn_threshold=0.7)
        panel = OverridePanel(cfg, adjudication_db)
        alert = {
            "type": "alert",
            "alert_id": "alert-002",
            "agent_did": agents[0]["agent_did"],
            "quality_score": 0.5,  # ≥ freeze(0.3) but < warn(0.7)
            "severity": "WARNING",
        }
        decision = panel.layer1_evaluate(alert)
        assert decision.action == "NEEDS_REVIEW"
        assert decision.severity == "WARNING"

    def test_coordination_flag_and_delay(self, adjudication_db, agents, config):
        """Coordination flag with score > threshold → FLAG_AND_DELAY."""
        panel = OverridePanel(config, adjudication_db)
        flag = {
            "type": "flag",
            "flag_id": "flag-001",
            "agent_did_1": agents[0]["agent_did"],
            "agent_did_2": agents[1]["agent_did"],
            "score": 0.85,  # above coordination_threshold (0.7)
        }
        decision = panel.layer1_evaluate(flag)
        assert decision.action == "FLAG_AND_DELAY"
        assert decision.severity == "WARNING"

    def test_sustained_failure_slash(self, adjudication_db, agents, seeded_task, config):
        """Reputation below sanction_floor + 3 consecutive failures → SLASH."""
        agent_did = agents[0]["agent_did"]

        conn = sqlite3.connect(str(adjudication_db))
        conn.execute("PRAGMA foreign_keys = ON")

        # Set agent reputation below sanction_floor (0.1)
        conn.execute(
            "UPDATE agent_registry SET reputation_score = 0.05 WHERE agent_did = ?",
            (agent_did,),
        )

        # Create 3 CRITICAL alerts for tasks assigned to this agent
        for i in range(3):
            task_id = f"slash-task-{i}"
            # Create task assignments
            conn.execute(
                "INSERT OR IGNORE INTO task_assignment "
                "(task_id, session_id, node_id, agent_did, status) "
                "VALUES (?, ?, ?, ?, 'committed')",
                (task_id, seeded_task["session_id"], seeded_task["node_id"], agent_did),
            )
            conn.execute(
                "INSERT INTO guardian_alert "
                "(alert_id, task_id, alert_type, severity, details) "
                "VALUES (?, ?, 'schema_failure', 'CRITICAL', 'test')",
                (f"slash-alert-{i}", task_id),
            )
        conn.commit()
        conn.close()

        panel = OverridePanel(config, adjudication_db)
        alert = {
            "type": "alert",
            "alert_id": "alert-slash",
            "agent_did": agent_did,
            "quality_score": 0.5,
            "severity": "CRITICAL",
        }
        decision = panel.layer1_evaluate(alert)
        assert decision.action == "SLASH"
        assert decision.severity == "CRITICAL"

    def test_clean_record_dismiss(self, adjudication_db, agents, config):
        """Agent with clean record and good quality → DISMISS."""
        panel = OverridePanel(config, adjudication_db)
        alert = {
            "type": "alert",
            "alert_id": "alert-clean",
            "agent_did": agents[0]["agent_did"],
            "quality_score": 0.95,  # above warn_threshold
            "severity": "INFO",
        }
        decision = panel.layer1_evaluate(alert)
        assert decision.action == "DISMISS"
        assert decision.severity == "INFO"
