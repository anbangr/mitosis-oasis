"""HHI (Herfindahl-Hirschman Index) tests — 4 tests."""
import pytest

from oasis.governance.fairness import hhi


def test_perfect_distribution():
    """p producers each with 1/p share → HHI = 1/p."""
    p = 5
    shares = [1.0 / p] * p
    result = hhi(shares)
    assert abs(result - 1.0 / p) < 1e-9


def test_monopoly():
    """One producer holds everything → HHI = 1.0."""
    assert hhi([1.0]) == 1.0


def test_known_two_producer_split():
    """Two producers: 70/30 split → HHI = 0.49 + 0.09 = 0.58."""
    result = hhi([0.7, 0.3])
    assert abs(result - 0.58) < 1e-9


def test_known_five_producer_asymmetric():
    """Five producers: [0.4, 0.3, 0.15, 0.1, 0.05] → known HHI."""
    shares = [0.4, 0.3, 0.15, 0.1, 0.05]
    expected = 0.16 + 0.09 + 0.0225 + 0.01 + 0.0025  # = 0.285
    result = hhi(shares)
    assert abs(result - expected) < 1e-9
