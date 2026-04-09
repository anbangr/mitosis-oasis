"""Override Panel — two-layer adjudication engine (deterministic + optional LLM).

Layer 1: Deterministic rule evaluation against thresholds.
Layer 2: Optional LLM advisory for borderline (NEEDS_REVIEW) cases.
"""
from __future__ import annotations

import sqlite3
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Union

from oasis.config import PlatformConfig
from oasis.adjudication.sanctions import AdjudicationDecision
from oasis.governance.clerks.llm_interface import LLMInterface


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class DeterministicDecision:
    """Result of Layer 1 deterministic evaluation."""

    action: str  # FREEZE, NEEDS_REVIEW, FLAG_AND_DELAY, SLASH, DISMISS
    reason: str
    severity: str


@dataclass
class LLMAdvisory:
    """Result of Layer 2 LLM evaluation (only for NEEDS_REVIEW cases)."""

    recommendation: str
    reasoning: str


# ---------------------------------------------------------------------------
# OverridePanel
# ---------------------------------------------------------------------------

class OverridePanel:
    """Two-layer adjudication panel (same pattern as governance clerks).

    Layer 1 — deterministic rules against configured thresholds.
    Layer 2 — optional LLM advisory for borderline cases.
    """

    def __init__(
        self,
        config: PlatformConfig,
        db_path: Union[str, Path],
        llm_enabled: bool = False,
        llm: LLMInterface | None = None,
    ) -> None:
        self.config = config
        self.db_path = str(db_path)
        self.llm_enabled = llm_enabled
        self.llm = llm

    def layer1_evaluate(self, alert_or_flag: dict) -> DeterministicDecision:
        """Evaluate an alert or coordination flag against deterministic rules.

        Parameters
        ----------
        alert_or_flag : dict
            Must contain ``type`` ("alert" or "flag") plus type-specific fields:
            - alert: quality_score, agent_did
            - flag:  kendall_tau / score, agent_did_1, agent_did_2
        """
        kind = alert_or_flag.get("type", "alert")

        if kind == "flag":
            return self._evaluate_coordination_flag(alert_or_flag)

        # Guardian alert path
        quality = alert_or_flag.get("quality_score", 1.0)
        agent_did = alert_or_flag.get("agent_did", "")

        # Check for sustained performance failure first
        if self._check_sustained_failure(agent_did):
            return DeterministicDecision(
                action="SLASH",
                reason="Reputation below sanction floor with consecutive failures",
                severity="CRITICAL",
            )

        if quality < self.config.freeze_threshold:
            # Below freeze threshold — immediate freeze
            severity = alert_or_flag.get("severity", "CRITICAL")
            return DeterministicDecision(
                action="FREEZE",
                reason=f"Quality {quality:.2f} below freeze threshold {self.config.freeze_threshold}",
                severity=severity,
            )

        if quality < self.config.warn_threshold:
            # Between freeze and warn thresholds — needs review
            return DeterministicDecision(
                action="NEEDS_REVIEW",
                reason=f"Quality {quality:.2f} borderline (freeze={self.config.freeze_threshold}, warn={self.config.warn_threshold})",
                severity="WARNING",
            )

        # Above warn threshold — dismiss
        return DeterministicDecision(
            action="DISMISS",
            reason="Quality within acceptable range",
            severity="INFO",
        )

    def layer2_evaluate(
        self,
        context: dict,
        layer1_decision: DeterministicDecision,
    ) -> LLMAdvisory | None:
        """Evaluate borderline cases using LLM (only when NEEDS_REVIEW).

        Returns None if LLM is disabled or layer1 decision is not NEEDS_REVIEW.
        """
        if not self.llm_enabled or self.llm is None:
            return None

        if layer1_decision.action != "NEEDS_REVIEW":
            return None

        prompt = (
            f"Evaluate this borderline adjudication case.\n"
            f"Layer 1 reason: {layer1_decision.reason}\n"
            f"Quality score: {context.get('quality_score', 'N/A')}\n"
            f"Agent: {context.get('agent_did', 'N/A')}\n"
            f"Deliberation transcript: {context.get('transcript', 'N/A')}\n"
            f"Appeal evidence: {context.get('appeal_evidence', 'N/A')}\n"
            f"Provide recommendation: DISMISS or ESCALATE."
        )

        response = self.llm.query(prompt, context)
        return LLMAdvisory(
            recommendation=response,
            reasoning=f"LLM evaluation of borderline case: {layer1_decision.reason}",
        )

    def decide(self, alert_or_flag: dict) -> AdjudicationDecision:
        """Full adjudication: Layer 1 + optional Layer 2 → stored decision."""
        layer1 = self.layer1_evaluate(alert_or_flag)

        # Layer 2 only for NEEDS_REVIEW
        advisory = self.layer2_evaluate(alert_or_flag, layer1)

        # Record decision
        conn = self._connect()
        try:
            decision_id = f"dec-{uuid.uuid4().hex[:8]}"
            alert_id = alert_or_flag.get("alert_id")
            flag_id = alert_or_flag.get("flag_id")
            agent_did = (
                alert_or_flag.get("agent_did")
                or alert_or_flag.get("agent_did_1", "unknown")
            )

            layer2_text = None
            if advisory is not None:
                layer2_text = f"{advisory.recommendation}: {advisory.reasoning}"

            conn.execute(
                "INSERT INTO adjudication_decision "
                "(decision_id, alert_id, flag_id, agent_did, decision_type, "
                "severity, reason, layer1_result, layer2_advisory) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    decision_id,
                    alert_id,
                    flag_id,
                    agent_did,
                    layer1.action.lower(),
                    layer1.severity,
                    layer1.reason,
                    layer1.action,
                    layer2_text,
                ),
            )
            conn.commit()

            return AdjudicationDecision(
                decision_id=decision_id,
                alert_id=alert_id,
                flag_id=flag_id,
                agent_did=agent_did,
                decision_type=layer1.action.lower(),
                severity=layer1.severity,
                reason=layer1.reason,
                layer1_result=layer1.action,
                layer2_advisory=layer2_text,
            )
        finally:
            conn.close()

    def process_batch(
        self,
        alerts: list[dict],
        flags: list[dict],
    ) -> list[AdjudicationDecision]:
        """Process a batch of alerts and flags, returning all decisions."""
        decisions: list[AdjudicationDecision] = []
        for alert in alerts:
            alert.setdefault("type", "alert")
            decisions.append(self.decide(alert))
        for flag in flags:
            flag.setdefault("type", "flag")
            decisions.append(self.decide(flag))
        return decisions

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _evaluate_coordination_flag(self, flag: dict) -> DeterministicDecision:
        """Evaluate a coordination flag against the coordination threshold."""
        score = flag.get("score", flag.get("kendall_tau", 0.0))
        if score > self.config.coordination_threshold:
            return DeterministicDecision(
                action="FLAG_AND_DELAY",
                reason=f"Coordination score {score:.2f} exceeds threshold {self.config.coordination_threshold}",
                severity="WARNING",
            )
        return DeterministicDecision(
            action="DISMISS",
            reason=f"Coordination score {score:.2f} within acceptable range",
            severity="INFO",
        )

    def _check_sustained_failure(self, agent_did: str) -> bool:
        """Check if agent has reputation below sanction floor AND ≥3 consecutive failures."""
        if not agent_did:
            return False

        conn = self._connect()
        try:
            # Check reputation
            agent = conn.execute(
                "SELECT reputation_score FROM agent_registry WHERE agent_did = ?",
                (agent_did,),
            ).fetchone()
            if agent is None:
                return False

            reputation = agent["reputation_score"]
            if reputation >= self.config.sanction_floor:
                return False

            # Count consecutive failures from guardian_alert
            alerts = conn.execute(
                "SELECT severity FROM guardian_alert "
                "WHERE task_id IN ("
                "  SELECT task_id FROM task_assignment WHERE agent_did = ?"
                ") ORDER BY created_at DESC LIMIT 3",
                (agent_did,),
            ).fetchall()

            if len(alerts) < 3:
                return False

            return all(a["severity"] == "CRITICAL" for a in alerts)
        finally:
            conn.close()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.execute("PRAGMA foreign_keys = ON")
        conn.row_factory = sqlite3.Row
        return conn
