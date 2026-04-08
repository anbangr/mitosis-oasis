"""HHI-based fairness metrics for bid concentration analysis.

Implements the fairness constraints from the AgentCity paper (§3.6):
- Herfindahl-Hirschman Index (HHI) for market concentration
- Normalised fairness scoring (0-1000 scale)
- Monopolisation bounds derived from constitutional minimums
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Dict, List, Optional


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------

@dataclass
class FairnessResult:
    """Outcome of a fairness check."""
    score: int          # 0-1000 normalised fairness score
    passed: bool        # True if score >= min_score
    max_share: float    # largest individual share
    violator: Optional[str]  # agent_did of the largest shareholder (if failed)


# ---------------------------------------------------------------------------
# HHI — Herfindahl-Hirschman Index
# ---------------------------------------------------------------------------

def hhi(shares: List[float]) -> float:
    """Compute the raw Herfindahl-Hirschman Index.

    ``shares`` is a list of market-share fractions that should sum to ~1.0.
    HHI = Σ(s_i²), ranging from 1/n (perfect equality) to 1.0 (monopoly).
    """
    return sum(s * s for s in shares)


# ---------------------------------------------------------------------------
# Normalised fairness score
# ---------------------------------------------------------------------------

def normalized_fairness_score(shares: List[float], num_producers: int) -> int:
    """Map raw HHI to a 0-1000 fairness score.

    Formula::

        score = round(1000 * (1 - HHI) / (1 - 1/p))

    where p = num_producers.  Score = 1000 when distribution is perfectly
    equal (HHI = 1/p) and 0 when one producer holds everything (HHI = 1).

    For p = 1 the score is trivially 1000 (no competition to measure).
    """
    if num_producers <= 1:
        return 1000
    raw = hhi(shares)
    min_hhi = 1.0 / num_producers
    max_hhi = 1.0
    if max_hhi == min_hhi:
        return 1000
    score = (1.0 - raw) / (1.0 - min_hhi)
    return max(0, min(1000, round(score * 1000)))


# ---------------------------------------------------------------------------
# Monopolisation bound
# ---------------------------------------------------------------------------

def monopolization_bound(num_producers: int, min_fairness: int = 600) -> float:
    """Maximum share any single producer can hold while maintaining fairness.

    Derived by solving for the max share *s* of one producer such that the
    *best-case* HHI (remaining 1-s split equally among p-1 others) still
    yields ``normalized_fairness_score >= min_fairness``.

    Returns the bound as a fraction in (0, 1].
    """
    if num_producers <= 1:
        return 1.0

    p = num_producers
    # Binary search for the largest s in [1/p, 1] where the score is still >= min_fairness
    lo, hi = 1.0 / p, 1.0
    for _ in range(100):  # converges well within 100 iterations
        mid = (lo + hi) / 2.0
        # Best-case: the remaining (1-mid) is split equally among (p-1) producers
        remaining_share = (1.0 - mid) / (p - 1)
        shares = [mid] + [remaining_share] * (p - 1)
        score = normalized_fairness_score(shares, p)
        if score >= min_fairness:
            lo = mid
        else:
            hi = mid
    return round(lo, 4)


# ---------------------------------------------------------------------------
# Fairness check
# ---------------------------------------------------------------------------

def check_fairness(
    bid_assignments: Dict[str, float],
    min_score: int = 600,
) -> FairnessResult:
    """Check whether a set of bid assignments passes the fairness threshold.

    ``bid_assignments`` maps agent_did → share of total work (fractions
    summing to ~1.0).

    Returns a ``FairnessResult``.
    """
    if not bid_assignments:
        return FairnessResult(score=1000, passed=True, max_share=0.0, violator=None)

    shares = list(bid_assignments.values())
    num_producers = len(shares)
    score = normalized_fairness_score(shares, num_producers)
    max_share = max(shares)
    max_agent = max(bid_assignments, key=bid_assignments.get)  # type: ignore[arg-type]
    passed = score >= min_score
    violator = max_agent if not passed else None

    return FairnessResult(
        score=score,
        passed=passed,
        max_share=max_share,
        violator=violator,
    )
