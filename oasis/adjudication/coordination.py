"""Coordination detection — wraps voting correlation and bidding overlap analysis.

Detects:
1. Voting coordination: reuses kendall_tau / coordination_detection from P3
2. Bidding coordination: Jaccard overlap on bid targets
"""
from __future__ import annotations

import sqlite3
import uuid
from dataclasses import dataclass
from itertools import combinations
from pathlib import Path
from typing import Union

import json

from oasis.governance.voting import kendall_tau


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class CoordinationFlag:
    """Record of a detected coordination pattern between two agents."""

    flag_id: str
    session_id: str
    agent_did_1: str
    agent_did_2: str
    flag_type: str  # "voting" or "bidding"
    score: float


# ---------------------------------------------------------------------------
# CoordinationDetector
# ---------------------------------------------------------------------------

class CoordinationDetector:
    """Detect coordination patterns (voting herding, bid collusion)."""

    def __init__(self, threshold: float = 0.8) -> None:
        self.threshold = threshold

    def detect_voting_coordination(
        self,
        session_id: str,
        db_path: Union[str, Path],
    ) -> list[tuple[str, str, float]]:
        """Detect pairwise voting coordination in a session.

        Compares each pair of agents' vote rankings using Kendall τ.
        Returns list of (agent1, agent2, tau) tuples that exceed the threshold.
        """
        conn = self._connect(db_path)
        try:
            # Vote table stores preference_ranking as a JSON array per agent
            rows = conn.execute(
                "SELECT agent_did, preference_ranking "
                "FROM vote WHERE session_id = ?",
                (session_id,),
            ).fetchall()

            if not rows:
                return []

            # Build per-agent rankings: agent → list of proposal IDs in rank order
            agent_rankings: dict[str, list[str]] = {}
            for row in rows:
                did = row["agent_did"]
                ranking = json.loads(row["preference_ranking"])
                agent_rankings[did] = ranking

            flagged: list[tuple[str, str, float]] = []
            agents = list(agent_rankings.keys())

            for a1, a2 in combinations(agents, 2):
                r1 = agent_rankings[a1]
                r2 = agent_rankings[a2]
                if set(r1) != set(r2):
                    continue
                tau = kendall_tau(r1, r2)
                if tau > self.threshold:
                    flagged.append((a1, a2, tau))

            return flagged
        finally:
            conn.close()

    def detect_bidding_coordination(
        self,
        session_id: str,
        db_path: Union[str, Path],
    ) -> list[tuple[str, str, float]]:
        """Detect pairwise bidding coordination via Jaccard similarity on bid targets.

        Returns list of (agent1, agent2, jaccard) tuples that exceed the threshold.
        """
        conn = self._connect(db_path)
        try:
            rows = conn.execute(
                "SELECT bidder_did, task_node_id FROM bid WHERE session_id = ?",
                (session_id,),
            ).fetchall()

            if not rows:
                return []

            # Build per-agent bid target sets
            agent_targets: dict[str, set[str]] = {}
            for row in rows:
                did = row["bidder_did"]
                if did not in agent_targets:
                    agent_targets[did] = set()
                agent_targets[did].add(row["task_node_id"])

            flagged: list[tuple[str, str, float]] = []
            agents = list(agent_targets.keys())

            for a1, a2 in combinations(agents, 2):
                jaccard = self.jaccard_similarity(
                    agent_targets[a1], agent_targets[a2]
                )
                if jaccard > self.threshold:
                    flagged.append((a1, a2, jaccard))

            return flagged
        finally:
            conn.close()

    def flag_pairs(
        self,
        session_id: str,
        db_path: Union[str, Path],
    ) -> list[CoordinationFlag]:
        """Run both detectors and write flags to the coordination_flag table.

        Returns the list of all flags written.
        """
        flags: list[CoordinationFlag] = []

        # Voting coordination
        voting_pairs = self.detect_voting_coordination(session_id, db_path)
        for a1, a2, tau in voting_pairs:
            flag = self._write_flag(
                session_id, a1, a2, "voting", tau, db_path
            )
            flags.append(flag)

        # Bidding coordination
        bidding_pairs = self.detect_bidding_coordination(session_id, db_path)
        for a1, a2, jaccard in bidding_pairs:
            flag = self._write_flag(
                session_id, a1, a2, "bidding", jaccard, db_path
            )
            flags.append(flag)

        return flags

    @staticmethod
    def jaccard_similarity(set_a: set, set_b: set) -> float:
        """Compute Jaccard similarity: |A ∩ B| / |A ∪ B|."""
        if not set_a and not set_b:
            return 0.0
        intersection = len(set_a & set_b)
        union = len(set_a | set_b)
        return intersection / union

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _write_flag(
        self,
        session_id: str,
        agent_did_1: str,
        agent_did_2: str,
        flag_type: str,
        score: float,
        db_path: Union[str, Path],
    ) -> CoordinationFlag:
        """Write a coordination flag to the database."""
        flag_id = f"flag-{uuid.uuid4().hex[:8]}"
        conn = self._connect(db_path)
        try:
            conn.execute(
                "INSERT INTO coordination_flag "
                "(flag_id, session_id, agent_did_1, agent_did_2, flag_type, score) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (flag_id, session_id, agent_did_1, agent_did_2, flag_type, score),
            )
            conn.commit()
            return CoordinationFlag(
                flag_id=flag_id,
                session_id=session_id,
                agent_did_1=agent_did_1,
                agent_did_2=agent_did_2,
                flag_type=flag_type,
                score=score,
            )
        finally:
            conn.close()

    @staticmethod
    def _connect(db_path: Union[str, Path]) -> sqlite3.Connection:
        conn = sqlite3.connect(str(db_path))
        conn.execute("PRAGMA foreign_keys = ON")
        conn.row_factory = sqlite3.Row
        return conn
