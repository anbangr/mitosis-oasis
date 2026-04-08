"""Copeland voting with Minimax tie-breaking, Kendall τ, and coordination detection.

Implements the democratic voting protocol from the AgentCity paper (§3.5):
- Copeland method: pairwise comparison scoring
- Minimax tie-break: smallest worst pairwise defeat
- Kendall τ: rank correlation for deliberation analysis
- Coordination detection: herding/convergence detection via τ shifts
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from itertools import combinations
from typing import Dict, List, Optional, Tuple


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------

@dataclass
class VotingResult:
    """Outcome of a Copeland election."""
    winner: Optional[str]
    scores: Dict[str, float]
    pairwise_matrix: Dict[Tuple[str, str], int]
    tiebreak_used: bool


# ---------------------------------------------------------------------------
# Ballot validation
# ---------------------------------------------------------------------------

def validate_ballot(ranking: List[str], candidates: List[str]) -> Tuple[bool, str]:
    """Validate a ballot is a complete ranking of all candidates.

    Returns (True, "") on success, (False, reason) on failure.
    """
    if not ranking:
        return False, "Empty ranking"
    if len(ranking) != len(candidates):
        return False, f"Incomplete ranking: got {len(ranking)}, expected {len(candidates)}"
    if len(set(ranking)) != len(ranking):
        return False, "Duplicate candidates in ranking"
    unknown = set(ranking) - set(candidates)
    if unknown:
        return False, f"Unknown candidates: {unknown}"
    return True, ""


# ---------------------------------------------------------------------------
# Copeland voting
# ---------------------------------------------------------------------------

class CopelandVoting:
    """Copeland method with Minimax tie-breaking.

    Usage::

        cv = CopelandVoting(candidates=["A", "B", "C"])
        cv.add_ballot("agent-1", ["A", "B", "C"])
        cv.add_ballot("agent-2", ["B", "C", "A"])
        cv.add_ballot("agent-3", ["A", "C", "B"])
        result = cv.result()
    """

    def __init__(self, candidates: List[str]) -> None:
        self.candidates = list(candidates)
        self.ballots: Dict[str, List[str]] = {}

    def add_ballot(self, agent_did: str, ranking: List[str]) -> None:
        """Record an ordinal ballot from an agent.

        Raises ``ValueError`` if the ballot is invalid.
        """
        ok, reason = validate_ballot(ranking, self.candidates)
        if not ok:
            raise ValueError(reason)
        self.ballots[agent_did] = list(ranking)

    def compute_pairwise_matrix(self) -> Dict[Tuple[str, str], int]:
        """Build an NxN pairwise-win count matrix.

        ``matrix[(A, B)]`` = number of ballots that rank A above B.
        """
        matrix: Dict[Tuple[str, str], int] = {}
        for a in self.candidates:
            for b in self.candidates:
                matrix[(a, b)] = 0

        for ranking in self.ballots.values():
            pos = {c: i for i, c in enumerate(ranking)}
            for a, b in combinations(self.candidates, 2):
                if pos[a] < pos[b]:
                    matrix[(a, b)] += 1
                else:
                    matrix[(b, a)] += 1

        return matrix

    def copeland_scores(self) -> Dict[str, float]:
        """Compute Copeland scores: +1 for pairwise win, 0 for tie, -1 for loss."""
        matrix = self.compute_pairwise_matrix()
        scores: Dict[str, float] = {c: 0.0 for c in self.candidates}

        for a, b in combinations(self.candidates, 2):
            wins_a = matrix[(a, b)]
            wins_b = matrix[(b, a)]
            if wins_a > wins_b:
                scores[a] += 1.0
                scores[b] -= 1.0
            elif wins_b > wins_a:
                scores[b] += 1.0
                scores[a] -= 1.0
            # tie: both stay at 0 for this pair

        return scores

    def minimax_tiebreak(self, tied_candidates: List[str]) -> str:
        """Break a tie using minimax: choose the candidate whose worst
        pairwise defeat is smallest.

        Among the *tied_candidates*, for each candidate compute the maximum
        number of votes any opponent received against them. The candidate
        with the smallest such maximum wins.
        """
        matrix = self.compute_pairwise_matrix()
        best_candidate = tied_candidates[0]
        best_worst_defeat = math.inf

        for c in tied_candidates:
            worst_defeat = 0
            for opp in self.candidates:
                if opp == c:
                    continue
                defeats = matrix[(opp, c)]
                if defeats > worst_defeat:
                    worst_defeat = defeats
            if worst_defeat < best_worst_defeat:
                best_worst_defeat = worst_defeat
                best_candidate = c
            elif worst_defeat == best_worst_defeat:
                # Deterministic fallback: lexicographic
                if c < best_candidate:
                    best_candidate = c

        return best_candidate

    def result(self) -> VotingResult:
        """Run the full Copeland election with minimax tiebreak if needed."""
        if not self.candidates:
            return VotingResult(winner=None, scores={}, pairwise_matrix={}, tiebreak_used=False)

        if len(self.candidates) == 1:
            return VotingResult(
                winner=self.candidates[0],
                scores={self.candidates[0]: 0.0},
                pairwise_matrix={},
                tiebreak_used=False,
            )

        scores = self.copeland_scores()
        matrix = self.compute_pairwise_matrix()
        max_score = max(scores.values())
        winners = [c for c in self.candidates if scores[c] == max_score]

        if len(winners) == 1:
            return VotingResult(
                winner=winners[0],
                scores=scores,
                pairwise_matrix=matrix,
                tiebreak_used=False,
            )

        # Tiebreak needed
        winner = self.minimax_tiebreak(winners)
        return VotingResult(
            winner=winner,
            scores=scores,
            pairwise_matrix=matrix,
            tiebreak_used=True,
        )

    def quorum_met(self, total_eligible: int, threshold: float = 0.6) -> bool:
        """Check whether enough ballots have been cast.

        Returns True when ``len(ballots) / total_eligible >= threshold``.
        """
        if total_eligible <= 0:
            return False
        return len(self.ballots) / total_eligible >= threshold


# ---------------------------------------------------------------------------
# Kendall τ correlation coefficient
# ---------------------------------------------------------------------------

def kendall_tau(ranking_a: List[str], ranking_b: List[str]) -> float:
    """Compute Kendall τ correlation between two rankings of the same items.

    Returns a value in [-1, 1]:
    - +1 = identical rankings
    - -1 = reversed rankings
    -  0 = no correlation

    Raises ``ValueError`` if the rankings don't contain the same elements.
    """
    if set(ranking_a) != set(ranking_b):
        raise ValueError("Rankings must contain the same elements")
    n = len(ranking_a)
    if n <= 1:
        return 1.0  # trivially identical

    pos_b = {item: i for i, item in enumerate(ranking_b)}
    concordant = 0
    discordant = 0

    for i in range(n):
        for j in range(i + 1, n):
            # In ranking_a, item at i is ranked above item at j.
            # Check if the same ordering holds in ranking_b.
            b_i = pos_b[ranking_a[i]]
            b_j = pos_b[ranking_a[j]]
            if b_i < b_j:
                concordant += 1
            else:
                discordant += 1

    total_pairs = n * (n - 1) // 2
    return (concordant - discordant) / total_pairs


# ---------------------------------------------------------------------------
# Coordination / herding detection
# ---------------------------------------------------------------------------

def coordination_detection(
    straw_poll_rankings: Dict[str, List[str]],
    final_rankings: Dict[str, List[str]],
    threshold: float = 0.8,
) -> Tuple[bool, float]:
    """Detect suspicious coordination/herding between straw poll and final vote.

    Compares each agent's straw-poll ranking to their final ranking via
    Kendall τ. If the *average* τ across all agents exceeds *threshold*,
    coordination is flagged.

    Returns ``(flagged: bool, avg_tau: float)``.
    """
    common_agents = set(straw_poll_rankings) & set(final_rankings)
    if not common_agents:
        return False, 0.0

    taus: List[float] = []
    for agent in common_agents:
        pre = straw_poll_rankings[agent]
        post = final_rankings[agent]
        if set(pre) == set(post):
            taus.append(kendall_tau(pre, post))

    if not taus:
        return False, 0.0

    avg_tau = sum(taus) / len(taus)
    return avg_tau >= threshold, avg_tau
