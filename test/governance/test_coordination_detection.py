"""Coordination / herding detection tests — 4 tests."""
from oasis.governance.voting import coordination_detection


def test_no_coordination():
    """Diverse pre/post rankings → low average τ → no flag."""
    straw = {
        "a1": ["A", "B", "C"],
        "a2": ["B", "C", "A"],
        "a3": ["C", "A", "B"],
    }
    final = {
        "a1": ["B", "A", "C"],
        "a2": ["C", "B", "A"],
        "a3": ["A", "C", "B"],
    }
    flagged, avg_tau = coordination_detection(straw, final, threshold=0.8)
    assert not flagged
    assert avg_tau < 0.8


def test_suspicious_convergence():
    """All agents keep their rankings identical → avg τ = 1.0 → flagged."""
    rankings = {"a1": ["A", "B", "C"], "a2": ["A", "B", "C"], "a3": ["A", "B", "C"]}
    flagged, avg_tau = coordination_detection(rankings, rankings, threshold=0.8)
    assert flagged
    assert avg_tau == 1.0


def test_all_identical_pre_post():
    """Pre and post rankings identical for each agent (maximum herding) → flagged."""
    straw = {"a1": ["X", "Y", "Z"], "a2": ["Z", "Y", "X"]}
    final = {"a1": ["X", "Y", "Z"], "a2": ["Z", "Y", "X"]}
    flagged, avg_tau = coordination_detection(straw, final, threshold=0.8)
    assert flagged
    assert avg_tau == 1.0


def test_threshold_sensitivity():
    """With a very high threshold, even moderate correlation passes."""
    straw = {"a1": ["A", "B", "C"]}
    final = {"a1": ["A", "C", "B"]}
    # τ = 1/3 for this pair
    flagged_low, _ = coordination_detection(straw, final, threshold=0.3)
    flagged_high, _ = coordination_detection(straw, final, threshold=0.5)
    assert flagged_low  # 1/3 >= 0.3
    assert not flagged_high  # 1/3 < 0.5
