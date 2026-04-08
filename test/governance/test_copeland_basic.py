"""Basic Copeland voting tests — 5 tests."""
from oasis.governance.voting import CopelandVoting


def test_three_candidate_clear_winner():
    """A has majority pairwise wins → clear Copeland winner."""
    cv = CopelandVoting(candidates=["A", "B", "C"])
    cv.add_ballot("v1", ["A", "B", "C"])
    cv.add_ballot("v2", ["A", "C", "B"])
    cv.add_ballot("v3", ["B", "A", "C"])
    result = cv.result()
    assert result.winner == "A"
    assert not result.tiebreak_used


def test_condorcet_winner_found():
    """The Condorcet winner (beats every other candidate pairwise) wins."""
    cv = CopelandVoting(candidates=["A", "B", "C"])
    # A beats B in 2 of 3, A beats C in 2 of 3 → Condorcet winner
    cv.add_ballot("v1", ["A", "B", "C"])
    cv.add_ballot("v2", ["A", "C", "B"])
    cv.add_ballot("v3", ["B", "C", "A"])
    result = cv.result()
    assert result.winner == "A"
    scores = result.scores
    # A should have highest score
    assert scores["A"] > scores["B"]
    assert scores["A"] > scores["C"]


def test_all_tied():
    """Condorcet cycle with 3 candidates → all tied, minimax tiebreak used."""
    cv = CopelandVoting(candidates=["A", "B", "C"])
    cv.add_ballot("v1", ["A", "B", "C"])
    cv.add_ballot("v2", ["B", "C", "A"])
    cv.add_ballot("v3", ["C", "A", "B"])
    result = cv.result()
    # All scores should be equal (each wins 1, loses 1 → net 0)
    assert result.scores["A"] == result.scores["B"] == result.scores["C"] == 0.0
    assert result.tiebreak_used
    assert result.winner is not None


def test_single_candidate():
    """Single candidate always wins, no tiebreak."""
    cv = CopelandVoting(candidates=["A"])
    result = cv.result()
    assert result.winner == "A"
    assert not result.tiebreak_used


def test_two_candidate():
    """Two-candidate election — simple majority."""
    cv = CopelandVoting(candidates=["A", "B"])
    cv.add_ballot("v1", ["A", "B"])
    cv.add_ballot("v2", ["A", "B"])
    cv.add_ballot("v3", ["B", "A"])
    result = cv.result()
    assert result.winner == "A"
    assert not result.tiebreak_used
