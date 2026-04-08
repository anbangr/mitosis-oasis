"""Kendall τ correlation coefficient tests — 5 tests."""
import pytest

from oasis.governance.voting import kendall_tau


def test_identical_rankings():
    """Identical rankings → τ = 1.0."""
    assert kendall_tau(["A", "B", "C", "D"], ["A", "B", "C", "D"]) == 1.0


def test_reversed_rankings():
    """Completely reversed → τ = -1.0."""
    assert kendall_tau(["A", "B", "C", "D"], ["D", "C", "B", "A"]) == -1.0


def test_partial_agreement():
    """Partial agreement → -1 < τ < 1."""
    tau = kendall_tau(["A", "B", "C", "D"], ["A", "C", "B", "D"])
    assert -1.0 < tau < 1.0


def test_single_element():
    """Single element → trivially identical → τ = 1.0."""
    assert kendall_tau(["A"], ["A"]) == 1.0


def test_known_hand_computed():
    """Hand-computed example: [A,B,C] vs [A,C,B].
    Pairs: (A,B) concordant, (A,C) concordant, (B,C) discordant.
    τ = (2-1)/3 = 1/3."""
    tau = kendall_tau(["A", "B", "C"], ["A", "C", "B"])
    assert abs(tau - 1 / 3) < 1e-9
