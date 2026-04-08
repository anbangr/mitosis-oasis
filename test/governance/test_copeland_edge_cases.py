"""Copeland edge case tests — 3 tests."""
from oasis.governance.voting import CopelandVoting


def test_empty_ballots():
    """No ballots cast — result still computed from candidates."""
    cv = CopelandVoting(candidates=["A", "B", "C"])
    result = cv.result()
    # All scores should be 0 (no pairwise data)
    assert all(v == 0.0 for v in result.scores.values())
    # Tiebreak used because all tied
    assert result.tiebreak_used
    assert result.winner is not None


def test_single_voter():
    """A single voter determines the outcome."""
    cv = CopelandVoting(candidates=["A", "B", "C"])
    cv.add_ballot("sole-voter", ["B", "A", "C"])
    result = cv.result()
    assert result.winner == "B"
    assert not result.tiebreak_used


def test_all_identical_rankings():
    """All voters submit the same ranking → clear winner, no tiebreak."""
    cv = CopelandVoting(candidates=["A", "B", "C"])
    for i in range(10):
        cv.add_ballot(f"v{i}", ["C", "A", "B"])
    result = cv.result()
    assert result.winner == "C"
    assert not result.tiebreak_used
