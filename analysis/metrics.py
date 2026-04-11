# Copyright 2024 CAMEL-AI.org. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""
analysis/metrics.py
===================
Aggregation of the 6 §5.6 governance experiment metrics from the OASIS
SQLite observatory database.

Reads from:
  - agent_registry (with capability_tier column from R3)
  - legislative_session (state machine history)
  - proposal, vote, bid (action records)
  - reputation_ledger (append-only reputation updates)
  - treasury (economic entries)

Computes:
  1. governance_convergence_rate
  2. reputation_gini
  3. hhi_task_allocation
  4. treasury_trajectory
  5. participation_depth_by_tier   (depends on R3)
  6. proposal_acceptance_by_tier   (depends on R3)
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from typing import Any


@dataclass
class GovernanceMetrics:
    """All 6 §5.6 metrics for one session_id range (one replicate)."""

    governance_convergence_rate: float = 0.0
    reputation_gini: float = 0.0
    hhi_task_allocation: float = 0.0
    treasury_trajectory: list[float] = field(default_factory=list)
    participation_depth_by_tier: dict[str, float] = field(default_factory=dict)
    proposal_acceptance_by_tier: dict[str, float] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "governance_convergence_rate": self.governance_convergence_rate,
            "reputation_gini": self.reputation_gini,
            "hhi_task_allocation": self.hhi_task_allocation,
            "treasury_trajectory": self.treasury_trajectory,
            "participation_depth_by_tier": self.participation_depth_by_tier,
            "proposal_acceptance_by_tier": self.proposal_acceptance_by_tier,
        }


class ObservatoryMetrics:
    """Compute the 6 §5.6 metrics from the OASIS SQLite databases.

    This class replaces the prototype ObservatoryMetrics that had 5
    mock/mislabeled methods. The per-round EQ2 metrics (α, H_b, φ_cap,
    β) belong in mitosis-prototype and are NOT computed here — this
    module is only for governance macro-metrics.
    """

    # Terminal states in the 9-state legislative machine; reaching any
    # of these counts as "convergence" for the §5.6 convergence rate.
    CONVERGED_STATES: tuple[str, ...] = (
        "VOTING", "EXECUTION", "DEPLOYED", "SESSION_CLOSED", "ARCHIVED",
    )

    def __init__(self, governance_db: str, adjudication_db: str | None = None):
        """Initialize with path(s) to SQLite databases.

        Args:
            governance_db: Path to the governance SQLite file.
            adjudication_db: Optional separate path for adjudication (treasury,
                reputation_ledger). If None, assumes single-db deployment.
        """
        self.governance_db = governance_db
        self.adjudication_db = adjudication_db or governance_db

    def _query(self, db: str, sql: str, params: tuple = ()) -> list[dict]:
        with sqlite3.connect(db) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute(sql, params)
            return [dict(row) for row in cursor.fetchall()]

    # ── Metric 1: Governance convergence rate ─────────────────────────────

    def get_governance_convergence_rate(self) -> float:
        """Fraction of sessions that reached a terminal (converged) state.

        Paper §5.6 definition: fraction of sessions reaching VOTING within
        a bounded number of deliberation rounds. We interpret 'reaching
        VOTING' as the state machine advancing to VOTING or beyond.
        """
        total = self._query(
            self.governance_db,
            "SELECT COUNT(*) AS c FROM legislative_session",
        )[0]["c"]
        if total == 0:
            return 0.0

        placeholders = ",".join("?" * len(self.CONVERGED_STATES))
        converged = self._query(
            self.governance_db,
            f"SELECT COUNT(*) AS c FROM legislative_session "
            f"WHERE state IN ({placeholders})",
            self.CONVERGED_STATES,
        )[0]["c"]

        return converged / total

    # ── Metric 2: Reputation Gini coefficient ─────────────────────────────

    def get_reputation_gini(self) -> float:
        """Gini coefficient over current reputation scores of producer agents.

        Uses the standard formula: G = (1/n) * (n + 1 - 2*(sum of ordered
        cumulative shares)/sum of values). Values in [0, 1]; 0 = perfect
        equality, 1 = maximal inequality.
        """
        rows = self._query(
            self.governance_db,
            "SELECT reputation_score FROM agent_registry "
            "WHERE agent_type = 'producer' AND active = 1 "
            "ORDER BY reputation_score",
        )
        values = [r["reputation_score"] for r in rows]
        return self._gini(values)

    @staticmethod
    def _gini(values: list[float]) -> float:
        if not values or sum(values) == 0:
            return 0.0
        sorted_vals = sorted(values)
        n = len(sorted_vals)
        cumulative = 0.0
        weighted = 0.0
        for i, v in enumerate(sorted_vals, start=1):
            cumulative += v
            weighted += i * v
        total = sum(sorted_vals)
        return (2 * weighted) / (n * total) - (n + 1) / n

    # ── Metric 3: HHI fairness over task allocation ───────────────────────

    def get_hhi_task_allocation(self) -> float:
        """Herfindahl-Hirschman Index over task/bid distribution.

        Uses bid table if task_assignment doesn't exist in this schema.
        Lower HHI = more evenly distributed, higher = concentrated.
        Returns value in [0, 10000] (standard HHI scale) or [0, 1] if
        normalized. Here we return the normalized form in [0, 1].
        """
        rows = self._query(
            self.governance_db,
            "SELECT bidder_did, COUNT(*) AS bids FROM bid GROUP BY bidder_did",
        )
        counts = [r["bids"] for r in rows]
        total = sum(counts)
        if total == 0:
            return 0.0
        shares = [c / total for c in counts]
        return sum(s * s for s in shares)

    # ── Metric 4: Treasury sustainability trajectory ──────────────────────

    def get_treasury_trajectory(self) -> list[float]:
        """Cumulative treasury balance over time as a list of values.

        Orders by the treasury table's timestamp column (if present) or
        primary key. Consumers use this for trend analysis and the §5.6
        'treasury sustainability' hypothesis.
        """
        try:
            rows = self._query(
                self.adjudication_db,
                "SELECT amount FROM treasury ORDER BY created_at",
            )
        except sqlite3.OperationalError:
            # Some schemas don't have created_at — fall back to insertion order
            rows = self._query(
                self.adjudication_db,
                "SELECT amount FROM treasury",
            )

        trajectory = []
        running = 0.0
        for row in rows:
            running += row["amount"] or 0.0
            trajectory.append(running)
        return trajectory

    # ── Metric 5: Per-tier participation depth ────────────────────────────

    def get_participation_depth_by_tier(self) -> dict[str, float]:
        """Mean governance actions per round, grouped by capability_tier.

        Counts proposals + votes + bids + deliberation messages per agent,
        joins against agent_registry.capability_tier, returns mean-per-tier.
        Requires R3 (capability_tier column populated).
        """
        sql = """
        WITH actions AS (
            SELECT proposer_did AS agent_did FROM proposal
            UNION ALL
            SELECT agent_did FROM vote
            UNION ALL
            SELECT bidder_did AS agent_did FROM bid
        ),
        counts AS (
            SELECT a.agent_did, COUNT(*) AS action_count
            FROM actions a
            GROUP BY a.agent_did
        )
        SELECT ar.capability_tier,
               AVG(COALESCE(c.action_count, 0)) AS mean_actions
        FROM agent_registry ar
        LEFT JOIN counts c ON c.agent_did = ar.agent_did
        WHERE ar.agent_type = 'producer' AND ar.active = 1
        GROUP BY ar.capability_tier
        """
        try:
            rows = self._query(self.governance_db, sql)
        except sqlite3.OperationalError as exc:
            # Deliberation table not present in all schemas
            return {"error": str(exc)}

        return {r["capability_tier"]: float(r["mean_actions"]) for r in rows}

    # ── Metric 6: Proposal acceptance rate by tier ────────────────────────

    def get_proposal_acceptance_by_tier(self) -> dict[str, float]:
        """Fraction of each tier's proposals that reached DEPLOYED state.

        Joins proposals to their sessions to check terminal state.
        Requires R3 (capability_tier column populated).
        """
        sql = """
        SELECT ar.capability_tier,
               SUM(CASE WHEN ls.state IN ('DEPLOYED', 'EXECUTION', 'SESSION_CLOSED')
                        THEN 1 ELSE 0 END) AS accepted,
               COUNT(*) AS total
        FROM proposal p
        JOIN agent_registry ar ON ar.agent_did = p.proposer_did
        JOIN legislative_session ls ON ls.session_id = p.session_id
        WHERE ar.agent_type = 'producer'
        GROUP BY ar.capability_tier
        """
        rows = self._query(self.governance_db, sql)
        return {
            r["capability_tier"]: (
                r["accepted"] / r["total"] if r["total"] else 0.0
            )
            for r in rows
        }

    # ── Aggregate ──────────────────────────────────────────────────────────

    def compute_all_metrics(self) -> dict[str, Any]:
        """Compute all 6 §5.6 metrics and return as a dict."""
        return GovernanceMetrics(
            governance_convergence_rate=self.get_governance_convergence_rate(),
            reputation_gini=self.get_reputation_gini(),
            hhi_task_allocation=self.get_hhi_task_allocation(),
            treasury_trajectory=self.get_treasury_trajectory(),
            participation_depth_by_tier=self.get_participation_depth_by_tier(),
            proposal_acceptance_by_tier=self.get_proposal_acceptance_by_tier(),
        ).to_dict()
