"""Monopolisation bound tests — 3 tests."""
import pytest

from oasis.governance.fairness import monopolization_bound


def test_p2_bound():
    """p=2 → bound ≈ 0.816 (each can hold up to ~81.6%)."""
    bound = monopolization_bound(2, min_fairness=600)
    assert abs(bound - 0.8165) < 0.01


def test_p5_bound():
    """p=5 → bound ≈ 0.72."""
    bound = monopolization_bound(5, min_fairness=600)
    assert abs(bound - 0.72) < 0.02


def test_p15_bound():
    """p=15 → bound ≈ 0.63."""
    bound = monopolization_bound(15, min_fairness=600)
    assert abs(bound - 0.63) < 0.03
