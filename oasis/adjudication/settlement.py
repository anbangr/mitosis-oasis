"""Settlement calculator — compute rewards, fees, reputation updates."""
from __future__ import annotations

import sqlite3
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Union

from oasis.config import PlatformConfig


@dataclass
class SettlementResult:
    """Immutable result of settling a task."""

    settlement_id: str
    task_id: str
    agent_did: str
    base_reward: float
    reputation_multiplier: float
    final_reward: float
    protocol_fee: float
    insurance_fee: float
    treasury_subsidy: float


class SettlementCalculator:
    """Compute and apply settlement for completed tasks.

    Settlement formula:
        R_base = bid × (1 - f_protocol - f_insurance)
        ψ(ρ)  = 1 + α × (ρ - ρ_neutral) / ρ_max    (ρ_max = 1.0)
        R_task = R_base × min(ψ, 1.0) + treasury_subsidy

    Where treasury_subsidy covers the premium when ψ > 1.0:
        subsidy = R_base × (ψ - 1.0)  if ψ > 1.0, else 0.0
    """

    RHO_MAX = 1.0  # maximum reputation score

    def __init__(self, config: PlatformConfig | None = None) -> None:
        self.config = config or PlatformConfig()

    def settle_task(
        self, task_id: str, db_path: Union[str, Path]
    ) -> SettlementResult:
        """Settle a completed task: compute reward, write records, update balances.

        Steps:
        1. Compute R_base = bid × (1 - f_protocol - f_insurance)
        2. Compute ψ(ρ) = 1 + α × (ρ - ρ_neutral) / ρ_max
        3. R_task = R_base × min(ψ, 1.0) + treasury_subsidy
        4. Write settlement row
        5. Update agent_balance
        6. Update reputation_ledger (EMA)
        7. Write treasury entries
        """
        conn = self._connect(db_path)
        try:
            # Look up task assignment
            task = conn.execute(
                "SELECT * FROM task_assignment WHERE task_id = ?",
                (task_id,),
            ).fetchone()
            if task is None:
                raise ValueError(f"Task not found: {task_id}")

            agent_did = task["agent_did"]

            # Look up bid amount (stake_amount from approved bid)
            bid = conn.execute(
                "SELECT stake_amount FROM bid "
                "WHERE session_id = ? AND task_node_id = ? AND bidder_did = ? "
                "AND status = 'approved'",
                (task["session_id"], task["node_id"], agent_did),
            ).fetchone()

            # Fall back to task_commitment stake if no bid found
            if bid is None:
                commitment = conn.execute(
                    "SELECT stake_amount FROM task_commitment WHERE task_id = ?",
                    (task_id,),
                ).fetchone()
                bid_amount = commitment["stake_amount"] if commitment else 0.5
            else:
                bid_amount = bid["stake_amount"]

            # Look up the node's token_budget as the bid value for reward
            node = conn.execute(
                "SELECT token_budget FROM dag_node WHERE node_id = ?",
                (task["node_id"],),
            ).fetchone()
            reward_basis = node["token_budget"] if node else bid_amount

            # Get agent reputation
            agent = conn.execute(
                "SELECT reputation_score FROM agent_registry WHERE agent_did = ?",
                (agent_did,),
            ).fetchone()
            reputation = agent["reputation_score"] if agent else 0.5

            # 1. Compute fees and base reward
            f_protocol = self.config.protocol_fee_rate
            f_insurance = self.config.insurance_fee_rate
            protocol_fee = reward_basis * f_protocol
            insurance_fee = reward_basis * f_insurance
            base_reward = reward_basis * (1 - f_protocol - f_insurance)

            # 2. Reputation multiplier
            psi = self.reputation_multiplier(reputation)

            # 3. Treasury subsidy and final reward
            subsidy = self.compute_treasury_subsidy(base_reward, psi)
            final_reward = base_reward * min(psi, 1.0) + subsidy

            # 4. Write settlement row
            settlement_id = f"settle-{uuid.uuid4().hex[:8]}"
            conn.execute(
                "INSERT INTO settlement "
                "(settlement_id, task_id, agent_did, base_reward, "
                "reputation_multiplier, final_reward, protocol_fee, "
                "insurance_fee, treasury_subsidy) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (settlement_id, task_id, agent_did, base_reward,
                 psi, final_reward, protocol_fee, insurance_fee, subsidy),
            )

            # 5. Update agent_balance — add final_reward to available
            self._ensure_balance(conn, agent_did)
            conn.execute(
                "UPDATE agent_balance "
                "SET total_balance = total_balance + ?, "
                "    available_balance = available_balance + ? "
                "WHERE agent_did = ?",
                (final_reward, final_reward, agent_did),
            )

            # 6. Update reputation_ledger (EMA)
            # Use quality_score from validation as performance_score
            validation = conn.execute(
                "SELECT quality_score FROM output_validation WHERE task_id = ?",
                (task_id,),
            ).fetchone()
            perf_score = validation["quality_score"] if validation else 0.7

            lam = self.config.reputation_alpha
            old_rep = reputation
            new_rep = lam * old_rep + (1 - lam) * perf_score

            conn.execute(
                "UPDATE agent_registry SET reputation_score = ? WHERE agent_did = ?",
                (new_rep, agent_did),
            )
            conn.execute(
                "INSERT INTO reputation_ledger "
                "(agent_did, old_score, new_score, performance_score, lambda, reason) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (agent_did, old_rep, new_rep, perf_score, lam, "settlement"),
            )

            # 7. Write treasury entries
            treasury_balance = self._get_treasury_balance(conn)

            # Protocol fee → treasury
            treasury_balance += protocol_fee
            conn.execute(
                "INSERT INTO treasury "
                "(task_id, entry_type, amount, balance_after) "
                "VALUES (?, 'protocol_fee', ?, ?)",
                (task_id, protocol_fee, treasury_balance),
            )

            # Insurance fee → treasury
            treasury_balance += insurance_fee
            conn.execute(
                "INSERT INTO treasury "
                "(task_id, entry_type, amount, balance_after) "
                "VALUES (?, 'insurance_fee', ?, ?)",
                (task_id, insurance_fee, treasury_balance),
            )

            # Subsidy (outflow from treasury)
            if subsidy > 0:
                treasury_balance -= subsidy
                conn.execute(
                    "INSERT INTO treasury "
                    "(task_id, agent_did, entry_type, amount, balance_after) "
                    "VALUES (?, ?, 'reputation_subsidy', ?, ?)",
                    (task_id, agent_did, -subsidy, treasury_balance),
                )

            conn.commit()
            return SettlementResult(
                settlement_id=settlement_id,
                task_id=task_id,
                agent_did=agent_did,
                base_reward=base_reward,
                reputation_multiplier=psi,
                final_reward=final_reward,
                protocol_fee=protocol_fee,
                insurance_fee=insurance_fee,
                treasury_subsidy=subsidy,
            )
        finally:
            conn.close()

    def reputation_multiplier(self, reputation: float) -> float:
        """Compute ψ(ρ) = 1 + α × (ρ - ρ_neutral) / ρ_max.

        Parameters
        ----------
        reputation : float
            Agent's current reputation score.

        Returns
        -------
        float
            The reputation multiplier ψ.
        """
        alpha = self.config.reputation_alpha
        neutral = self.config.reputation_neutral
        return 1.0 + alpha * (reputation - neutral) / self.RHO_MAX

    def compute_treasury_subsidy(self, base_reward: float, psi: float) -> float:
        """Compute treasury subsidy for high-reputation agents.

        When ψ > 1.0, the premium (ψ - 1.0) × R_base is funded from
        the treasury.  Otherwise returns 0.0.
        """
        if psi > 1.0:
            return base_reward * (psi - 1.0)
        return 0.0

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _ensure_balance(conn: sqlite3.Connection, agent_did: str) -> None:
        conn.execute(
            "INSERT OR IGNORE INTO agent_balance "
            "(agent_did, total_balance, locked_stake, available_balance) "
            "VALUES (?, 100.0, 0.0, 100.0)",
            (agent_did,),
        )

    @staticmethod
    def _get_treasury_balance(conn: sqlite3.Connection) -> float:
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
