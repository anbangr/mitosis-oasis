"""Sanction engine — freeze, slash, reputation reduction for misbehaving agents."""
from __future__ import annotations

import sqlite3
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Union

from oasis.config import PlatformConfig


@dataclass
class AdjudicationDecision:
    """Record of an adjudication / sanction decision."""

    decision_id: str
    alert_id: str | None
    flag_id: str | None
    agent_did: str
    decision_type: str
    severity: str
    reason: str | None
    layer1_result: str | None
    layer2_advisory: str | None
    created_at: str | None = None


class SanctionEngine:
    """Enforce sanctions: freeze agents, slash stakes, reduce reputation."""

    def __init__(self, config: PlatformConfig | None = None) -> None:
        self.config = config or PlatformConfig()

    def freeze_agent(
        self, agent_did: str, reason: str, db_path: Union[str, Path]
    ) -> AdjudicationDecision:
        """Set agent active=0, blocking them from new tasks."""
        conn = self._connect(db_path)
        try:
            conn.execute(
                "UPDATE agent_registry SET active = 0 WHERE agent_did = ?",
                (agent_did,),
            )
            decision = self._record_decision(
                conn,
                agent_did=agent_did,
                decision_type="freeze",
                severity="CRITICAL",
                reason=reason,
                layer1_result="frozen",
            )
            conn.commit()
            return decision
        finally:
            conn.close()

    def unfreeze_agent(
        self, agent_did: str, db_path: Union[str, Path]
    ) -> AdjudicationDecision:
        """Reactivate a frozen agent."""
        conn = self._connect(db_path)
        try:
            conn.execute(
                "UPDATE agent_registry SET active = 1 WHERE agent_did = ?",
                (agent_did,),
            )
            decision = self._record_decision(
                conn,
                agent_did=agent_did,
                decision_type="unfreeze",
                severity="INFO",
                reason="Agent reactivated",
                layer1_result="unfrozen",
            )
            conn.commit()
            return decision
        finally:
            conn.close()

    def slash_stake(
        self,
        agent_did: str,
        amount: float,
        reason: str,
        db_path: Union[str, Path],
    ) -> AdjudicationDecision:
        """Deduct from locked_stake and add slash_proceeds to treasury.

        If the agent's locked_stake is less than ``amount``, a partial
        slash is performed (whatever is available).
        """
        conn = self._connect(db_path)
        try:
            # Get current locked stake
            bal = conn.execute(
                "SELECT locked_stake FROM agent_balance WHERE agent_did = ?",
                (agent_did,),
            ).fetchone()
            locked = bal["locked_stake"] if bal else 0.0
            actual_slash = min(amount, locked)

            if actual_slash > 0:
                # Deduct from agent's locked stake and total balance
                conn.execute(
                    "UPDATE agent_balance "
                    "SET locked_stake = locked_stake - ?, "
                    "    total_balance = total_balance - ? "
                    "WHERE agent_did = ?",
                    (actual_slash, actual_slash, agent_did),
                )

                # Add to treasury as slash_proceeds
                treasury_balance = self._get_treasury_balance(conn)
                new_balance = treasury_balance + actual_slash
                conn.execute(
                    "INSERT INTO treasury "
                    "(agent_did, entry_type, amount, balance_after) "
                    "VALUES (?, 'slash_proceeds', ?, ?)",
                    (agent_did, actual_slash, new_balance),
                )

            decision = self._record_decision(
                conn,
                agent_did=agent_did,
                decision_type="slash",
                severity="CRITICAL",
                reason=f"{reason} (slashed {actual_slash:.2f})",
                layer1_result=f"slashed_{actual_slash:.2f}",
            )
            conn.commit()
            return decision
        finally:
            conn.close()

    def reduce_reputation(
        self,
        agent_did: str,
        performance_score: float,
        db_path: Union[str, Path],
    ) -> AdjudicationDecision:
        """EMA update: new_rep = λ * old_rep + (1-λ) * performance_score.

        λ (lambda) is taken from config.reputation_alpha (default 0.5).
        """
        lam = self.config.reputation_alpha
        conn = self._connect(db_path)
        try:
            # Get current reputation
            agent = conn.execute(
                "SELECT reputation_score FROM agent_registry WHERE agent_did = ?",
                (agent_did,),
            ).fetchone()
            old_rep = agent["reputation_score"] if agent else 0.5

            new_rep = lam * old_rep + (1 - lam) * performance_score

            # Update agent_registry
            conn.execute(
                "UPDATE agent_registry SET reputation_score = ? WHERE agent_did = ?",
                (new_rep, agent_did),
            )

            # Append to reputation_ledger
            conn.execute(
                "INSERT INTO reputation_ledger "
                "(agent_did, old_score, new_score, performance_score, lambda, reason) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (agent_did, old_rep, new_rep, performance_score, lam, "sanction_reputation_update"),
            )

            decision = self._record_decision(
                conn,
                agent_did=agent_did,
                decision_type="reputation_reduction",
                severity="WARNING",
                reason=f"EMA update: {old_rep:.4f} → {new_rep:.4f}",
                layer1_result=f"reputation_{new_rep:.4f}",
            )
            conn.commit()
            return decision
        finally:
            conn.close()

    def get_sanction_history(
        self, agent_did: str, db_path: Union[str, Path]
    ) -> list[AdjudicationDecision]:
        """Return all adjudication decisions for a given agent."""
        conn = self._connect(db_path)
        try:
            rows = conn.execute(
                "SELECT * FROM adjudication_decision "
                "WHERE agent_did = ? ORDER BY created_at DESC",
                (agent_did,),
            ).fetchall()
            return [
                AdjudicationDecision(
                    decision_id=r["decision_id"],
                    alert_id=r["alert_id"],
                    flag_id=r["flag_id"],
                    agent_did=r["agent_did"],
                    decision_type=r["decision_type"],
                    severity=r["severity"],
                    reason=r["reason"],
                    layer1_result=r["layer1_result"],
                    layer2_advisory=r["layer2_advisory"],
                    created_at=r["created_at"],
                )
                for r in rows
            ]
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _record_decision(
        self,
        conn: sqlite3.Connection,
        *,
        agent_did: str,
        decision_type: str,
        severity: str,
        reason: str,
        layer1_result: str,
        alert_id: str | None = None,
        flag_id: str | None = None,
    ) -> AdjudicationDecision:
        decision_id = f"dec-{uuid.uuid4().hex[:8]}"
        conn.execute(
            "INSERT INTO adjudication_decision "
            "(decision_id, alert_id, flag_id, agent_did, decision_type, "
            "severity, reason, layer1_result, layer2_advisory) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (decision_id, alert_id, flag_id, agent_did, decision_type,
             severity, reason, layer1_result, None),
        )
        return AdjudicationDecision(
            decision_id=decision_id,
            alert_id=alert_id,
            flag_id=flag_id,
            agent_did=agent_did,
            decision_type=decision_type,
            severity=severity,
            reason=reason,
            layer1_result=layer1_result,
            layer2_advisory=None,
        )

    @staticmethod
    def _get_treasury_balance(conn: sqlite3.Connection) -> float:
        """Compute current treasury balance from the ledger."""
        row = conn.execute(
            "SELECT balance_after FROM treasury ORDER BY entry_id DESC LIMIT 1"
        ).fetchone()
        return row["balance_after"] if row else 0.0

    @staticmethod
    def _connect(db_path: Union[str, Path]) -> sqlite3.Connection:
        conn = sqlite3.connect(str(db_path))
        conn.execute("PRAGMA foreign_keys = ON")
        conn.row_factory = sqlite3.Row
        return conn
