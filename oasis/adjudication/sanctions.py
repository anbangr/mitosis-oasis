"""Sanction engine — freeze, slash, reputation reduction for misbehaving agents."""

from __future__ import annotations

import sqlite3
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Union

from oasis.adjudication._constitution import _get_constitution_param
from oasis.adjudication.coi import ConflictedAdjudicatorError, is_conflicted
from oasis.adjudication.rotation import RotationViolationError, enforce_rotation
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

    def _check_coi(
        self,
        *,
        issued_by_did: str | None,
        mission_id: str | None,
        target_did: str,
        db_path: Union[str, Path],
        adj_db_path: Union[str, Path, None] = None,
        gov_db_path: Union[str, Path, None] = None,
    ) -> None:
        """Raise ConflictedAdjudicatorError if the adjudicator is conflicted."""
        if issued_by_did is None:
            return

        _adj_db = str(adj_db_path or db_path)
        _gov_db = str(gov_db_path or db_path)

        # Determine mission and agents in mission
        if mission_id is not None:
            _mission = mission_id
        else:
            # Infer mission from target_did's active assignment
            conn = sqlite3.connect(_gov_db)
            conn.row_factory = sqlite3.Row
            try:
                row = conn.execute(
                    "SELECT session_id FROM task_assignment "
                    "WHERE agent_did = ? AND status IN ('committed', 'running', 'assigned') "
                    "ORDER BY created_at DESC LIMIT 1",
                    (target_did,),
                ).fetchone()
                _mission = row["session_id"] if row else None
            finally:
                conn.close()

        # Gather agents in the mission. Split-DB production paths only check
        # an actual mission; legacy single-DB fixtures may omit task_assignment
        # rows, so keep the target as the minimal mission set there.
        conn = sqlite3.connect(_gov_db)
        conn.row_factory = sqlite3.Row
        try:
            if _mission is not None:
                rows = conn.execute(
                    "SELECT agent_did FROM task_assignment WHERE session_id = ?",
                    (_mission,),
                ).fetchall()
                agents_in_mission = {r["agent_did"] for r in rows}
            else:
                agents_in_mission = set()
            if _mission is not None or _gov_db == str(db_path):
                agents_in_mission.add(target_did)
        finally:
            conn.close()

        if is_conflicted(
            adjudicator_did=issued_by_did,
            mission_id=_mission,
            agents_in_mission=agents_in_mission,
            gov_db_path=_gov_db,
        ):
            raise ConflictedAdjudicatorError(
                f"adjudicator {issued_by_did} recused: owns agent in mission {_mission}"
            )

    def _check_rotation(
        self,
        *,
        issued_by_did: str | None,
        decision_type: str,
        adj_db_path: Union[str, Path],
        gov_db_path: Union[str, Path, None] = None,
    ) -> None:
        """Raise RotationViolationError if the adjudicator has exceeded the consecutive limit."""
        if issued_by_did is None:
            return

        _adj_db = str(adj_db_path)
        _gov_db = str(gov_db_path or adj_db_path)

        max_consecutive = int(
            _get_constitution_param(_gov_db, "rotation_max_consecutive", default=2.0)
        )
        result = enforce_rotation(
            adjudicator_did=issued_by_did,
            decision_type=decision_type,
            max_consecutive=max_consecutive,
            db_path=_adj_db,
        )
        if not result.allowed:
            raise RotationViolationError(result.reason)

    def freeze_agent(
        self,
        agent_did: str,
        reason: str,
        db_path: Union[str, Path],
        *,
        issued_by_did: str | None = None,
        mission_id: str | None = None,
        adj_db_path: Union[str, Path, None] = None,
        gov_db_path: Union[str, Path, None] = None,
    ) -> AdjudicationDecision:
        """Set agent active=0, blocking them from new tasks."""
        self._check_coi(
            issued_by_did=issued_by_did,
            mission_id=mission_id,
            target_did=agent_did,
            db_path=db_path,
            adj_db_path=adj_db_path,
            gov_db_path=gov_db_path,
        )
        self._check_rotation(
            issued_by_did=issued_by_did,
            decision_type="freeze",
            adj_db_path=adj_db_path or db_path,
            gov_db_path=gov_db_path,
        )

        conn = self._connect(db_path)
        try:
            self._ensure_agent_registry_row(conn, agent_did)
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
                issued_by_did=issued_by_did,
            )
            conn.commit()
            return decision
        finally:
            conn.close()

    def unfreeze_agent(
        self,
        agent_did: str,
        db_path: Union[str, Path],
        *,
        issued_by_did: str | None = None,
        adj_db_path: Union[str, Path, None] = None,
        gov_db_path: Union[str, Path, None] = None,
    ) -> AdjudicationDecision:
        """Reactivate a frozen agent."""
        self._check_rotation(
            issued_by_did=issued_by_did,
            decision_type="unfreeze",
            adj_db_path=adj_db_path or db_path,
            gov_db_path=gov_db_path,
        )
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
                issued_by_did=issued_by_did,
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
        *,
        issued_by_did: str | None = None,
        mission_id: str | None = None,
        adj_db_path: Union[str, Path, None] = None,
        gov_db_path: Union[str, Path, None] = None,
    ) -> AdjudicationDecision:
        """Deduct from locked_stake and split slash proceeds 50/50 between
        treasury and insurance_pool.

        If the agent's locked_stake is less than ``amount``, a partial
        slash is performed (whatever is available).

        Adjudicator-stake slashes (impeachment) are handled separately in
        Bundle 2 and remain 100% → treasury per spec §2.2.
        """
        self._check_coi(
            issued_by_did=issued_by_did,
            mission_id=mission_id,
            target_did=agent_did,
            db_path=db_path,
            adj_db_path=adj_db_path,
            gov_db_path=gov_db_path,
        )
        self._check_rotation(
            issued_by_did=issued_by_did,
            decision_type="slash",
            adj_db_path=adj_db_path or db_path,
            gov_db_path=gov_db_path,
        )

        conn = self._connect(db_path)
        try:
            self._ensure_agent_registry_row(conn, agent_did)
            # Get current locked stake
            bal = conn.execute(
                "SELECT locked_stake FROM agent_balance WHERE agent_did = ?",
                (agent_did,),
            ).fetchone()
            locked = bal["locked_stake"] if bal else 0.0
            actual_slash = min(amount, locked)

            # Record decision FIRST so decision_id is known for ledger entries
            decision = self._record_decision(
                conn,
                agent_did=agent_did,
                decision_type="slash",
                severity="CRITICAL",
                reason=f"{reason} (slashed {actual_slash:.2f})",
                layer1_result=f"slashed_{actual_slash:.2f}",
                issued_by_did=issued_by_did,
            )

            if actual_slash > 0:
                # Deduct from agent's locked stake and total balance
                conn.execute(
                    "UPDATE agent_balance "
                    "SET locked_stake = locked_stake - ?, "
                    "    total_balance = total_balance - ? "
                    "WHERE agent_did = ?",
                    (actual_slash, actual_slash, agent_did),
                )

                # Split 50/50 between treasury and insurance_pool
                treasury_share = actual_slash * 0.5
                insurance_share = actual_slash - treasury_share

                # Add to treasury as slash_proceeds
                treasury_balance = self._get_treasury_balance(conn)
                new_treasury_balance = treasury_balance + treasury_share
                conn.execute(
                    "INSERT INTO treasury "
                    "(agent_did, entry_type, amount, balance_after, decision_id) "
                    "VALUES (?, 'slash_proceeds', ?, ?, ?)",
                    (
                        agent_did,
                        treasury_share,
                        new_treasury_balance,
                        decision.decision_id,
                    ),
                )

                # Add to insurance_pool as slash_proceeds
                insurance_balance = self._get_insurance_balance(conn)
                new_insurance_balance = insurance_balance + insurance_share
                conn.execute(
                    "INSERT INTO insurance_pool "
                    "(agent_did, entry_type, amount, balance_after, decision_id) "
                    "VALUES (?, 'slash_proceeds', ?, ?, ?)",
                    (
                        agent_did,
                        insurance_share,
                        new_insurance_balance,
                        decision.decision_id,
                    ),
                )

            conn.commit()
            return decision
        finally:
            conn.close()

    def record_override(
        self,
        agent_did: str,
        reason: str,
        db_path: Union[str, Path],
        *,
        issued_by_did: str | None = None,
        mission_id: str | None = None,
        adj_db_path: Union[str, Path, None] = None,
        gov_db_path: Union[str, Path, None] = None,
    ) -> AdjudicationDecision:
        """Record an override-panel binding decision."""
        self._check_coi(
            issued_by_did=issued_by_did,
            mission_id=mission_id,
            target_did=agent_did,
            db_path=db_path,
            adj_db_path=adj_db_path,
            gov_db_path=gov_db_path,
        )
        self._check_rotation(
            issued_by_did=issued_by_did,
            decision_type="override",
            adj_db_path=adj_db_path or db_path,
            gov_db_path=gov_db_path,
        )

        conn = self._connect(db_path)
        try:
            self._ensure_agent_registry_row(conn, agent_did)
            decision = self._record_decision(
                conn,
                agent_did=agent_did,
                decision_type="override",
                severity="CRITICAL",
                reason=reason,
                layer1_result="override",
                issued_by_did=issued_by_did,
            )
            conn.commit()
            return decision
        finally:
            conn.close()

    def _compute_ema(self, old: float, score: float) -> float:
        """Compute EMA: new = λ × old + (1 − λ) × score.

        λ is taken from ``config.reputation_lambda``.
        """
        lam = self.config.reputation_lambda
        return lam * old + (1 - lam) * score

    def reduce_reputation(
        self,
        agent_did: str,
        performance_score: float,
        db_path: Union[str, Path],
    ) -> AdjudicationDecision:
        """EMA update: new_rep = λ * old_rep + (1-λ) * performance_score.

        λ (lambda) is taken from config.reputation_lambda (default 0.5).
        """
        lam = self.config.reputation_lambda
        conn = self._connect(db_path)
        try:
            # Get current reputation
            agent = conn.execute(
                "SELECT reputation_score FROM agent_registry WHERE agent_did = ?",
                (agent_did,),
            ).fetchone()
            old_rep = agent["reputation_score"] if agent else 0.5

            new_rep = self._compute_ema(old_rep, performance_score)

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
                (
                    agent_did,
                    old_rep,
                    new_rep,
                    performance_score,
                    lam,
                    "sanction_reputation_update",
                ),
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

    @staticmethod
    def _ensure_agent_registry_row(conn: sqlite3.Connection, agent_did: str) -> None:
        try:
            conn.execute(
                "INSERT OR IGNORE INTO agent_registry "
                "(agent_did, agent_type, display_name) VALUES (?, 'producer', ?)",
                (agent_did, agent_did),
            )
        except sqlite3.OperationalError:
            # Legacy adjudication-only fixtures may not carry agent_registry.
            pass

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
        issued_by_did: str | None = None,
    ) -> AdjudicationDecision:
        decision_id = f"dec-{uuid.uuid4().hex[:8]}"
        conn.execute(
            "INSERT INTO adjudication_decision "
            "(decision_id, alert_id, flag_id, agent_did, decision_type, "
            "severity, reason, layer1_result, layer2_advisory, issued_by_did) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                decision_id,
                alert_id,
                flag_id,
                agent_did,
                decision_type,
                severity,
                reason,
                layer1_result,
                None,
                issued_by_did,
            ),
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
    def _get_insurance_balance(conn: sqlite3.Connection) -> float:
        """Compute current insurance_pool balance from the ledger."""
        row = conn.execute(
            "SELECT balance_after FROM insurance_pool ORDER BY entry_id DESC LIMIT 1"
        ).fetchone()
        return row["balance_after"] if row else 0.0

    @staticmethod
    def _connect(db_path: Union[str, Path]) -> sqlite3.Connection:
        conn = sqlite3.connect(str(db_path))
        conn.execute("PRAGMA foreign_keys = ON")
        conn.row_factory = sqlite3.Row
        return conn
