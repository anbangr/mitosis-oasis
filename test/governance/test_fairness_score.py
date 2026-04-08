"""Normalised fairness score tests — 4 tests."""
from oasis.governance.fairness import normalized_fairness_score, monopolization_bound


def test_score_1000_for_equal_distribution():
    """Equal shares → HHI = 1/p → score = 1000."""
    p = 10
    shares = [1.0 / p] * p
    assert normalized_fairness_score(shares, p) == 1000


def test_score_0_for_monopoly():
    """One producer holds all → HHI = 1.0 → score = 0."""
    shares = [1.0]
    # With only 1 producer, there's no competition → trivially 1000
    # But if we pretend there are 5 producers (4 with 0):
    shares_5 = [1.0, 0.0, 0.0, 0.0, 0.0]
    assert normalized_fairness_score(shares_5, 5) == 0


def test_constitutional_minimum_600():
    """A distribution with score < 600 should fail the constitutional minimum."""
    # Very skewed: one agent dominates
    shares = [0.9, 0.05, 0.05]
    score = normalized_fairness_score(shares, 3)
    assert score < 600


def test_boundary_63_percent_for_p15():
    """At p=15, the monopolisation bound is ~63% — check boundary."""
    bound = monopolization_bound(15, min_fairness=600)
    # Construct shares at the bound
    remaining = (1.0 - bound) / 14
    shares = [bound] + [remaining] * 14
    score = normalized_fairness_score(shares, 15)
    assert score >= 600
    # Just above the bound should fail
    over = bound + 0.01
    remaining_over = (1.0 - over) / 14
    shares_over = [over] + [remaining_over] * 14
    score_over = normalized_fairness_score(shares_over, 15)
    assert score_over < 600
