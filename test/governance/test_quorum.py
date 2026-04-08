"""Quorum check tests — 4 tests."""
from oasis.governance.voting import CopelandVoting


def test_sixty_percent_met():
    """6 out of 10 eligible = 60% → quorum met."""
    cv = CopelandVoting(candidates=["A", "B"])
    for i in range(6):
        cv.add_ballot(f"v{i}", ["A", "B"])
    assert cv.quorum_met(total_eligible=10, threshold=0.6)


def test_fifty_nine_percent_fails():
    """59 out of 100 = 59% → quorum NOT met at 60%."""
    cv = CopelandVoting(candidates=["A", "B"])
    for i in range(59):
        cv.add_ballot(f"v{i}", ["A", "B"])
    assert not cv.quorum_met(total_eligible=100, threshold=0.6)


def test_exactly_sixty_percent():
    """Exactly 60% threshold boundary → quorum met."""
    cv = CopelandVoting(candidates=["A", "B"])
    for i in range(3):
        cv.add_ballot(f"v{i}", ["A", "B"])
    assert cv.quorum_met(total_eligible=5, threshold=0.6)


def test_all_vote():
    """100% participation → quorum always met."""
    cv = CopelandVoting(candidates=["A", "B"])
    for i in range(10):
        cv.add_ballot(f"v{i}", ["A", "B"])
    assert cv.quorum_met(total_eligible=10, threshold=0.6)
