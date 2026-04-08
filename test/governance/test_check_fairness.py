"""check_fairness integration tests — 3 tests."""
from oasis.governance.fairness import check_fairness


def test_passing_distribution():
    """Equal shares → passes fairness check."""
    assignments = {"a1": 0.25, "a2": 0.25, "a3": 0.25, "a4": 0.25}
    result = check_fairness(assignments, min_score=600)
    assert result.passed
    assert result.score == 1000
    assert result.violator is None


def test_failing_with_violator():
    """Highly concentrated → fails, violator identified."""
    assignments = {"a1": 0.9, "a2": 0.05, "a3": 0.05}
    result = check_fairness(assignments, min_score=600)
    assert not result.passed
    assert result.violator == "a1"
    assert result.max_share == 0.9


def test_edge_case_at_boundary():
    """Distribution near the fairness threshold boundary."""
    # 4 producers, one with slightly more
    assignments = {"a1": 0.35, "a2": 0.25, "a3": 0.20, "a4": 0.20}
    result = check_fairness(assignments, min_score=600)
    assert result.passed
    assert result.score >= 600
