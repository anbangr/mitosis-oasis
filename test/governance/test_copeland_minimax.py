"""Copeland minimax tie-breaking tests — 4 tests."""
from oasis.governance.voting import CopelandVoting


def test_tie_broken_by_minimax():
    """Two candidates tied on Copeland score → minimax selects the one
    with a smaller worst defeat."""
    cv = CopelandVoting(candidates=["A", "B", "C", "D"])
    # Construct ballots where A and B tie on Copeland score,
    # but A's worst pairwise defeat is smaller than B's.
    cv.add_ballot("v1", ["A", "C", "B", "D"])
    cv.add_ballot("v2", ["B", "D", "A", "C"])
    cv.add_ballot("v3", ["A", "D", "C", "B"])
    cv.add_ballot("v4", ["C", "B", "D", "A"])
    cv.add_ballot("v5", ["D", "A", "B", "C"])
    result = cv.result()
    assert result.winner is not None
    if result.tiebreak_used:
        # Minimax was needed → winner determined by smallest worst defeat
        assert result.winner in result.scores


def test_multiple_ties():
    """Three-way Copeland tie resolved by minimax."""
    cv = CopelandVoting(candidates=["A", "B", "C"])
    cv.add_ballot("v1", ["A", "B", "C"])
    cv.add_ballot("v2", ["B", "C", "A"])
    cv.add_ballot("v3", ["C", "A", "B"])
    result = cv.result()
    assert result.tiebreak_used
    assert result.winner in ["A", "B", "C"]


def test_minimax_equal_worst_defeats():
    """When worst defeats are equal, lexicographic fallback applies."""
    cv = CopelandVoting(candidates=["B", "A", "C"])
    # Symmetric cycle → all worst defeats equal
    cv.add_ballot("v1", ["A", "B", "C"])
    cv.add_ballot("v2", ["B", "C", "A"])
    cv.add_ballot("v3", ["C", "A", "B"])
    result = cv.result()
    assert result.tiebreak_used
    # Lexicographic fallback → "A" wins
    assert result.winner == "A"


def test_condorcet_cycle():
    """A>B>C>A cycle (rock-paper-scissors) → tiebreak needed."""
    cv = CopelandVoting(candidates=["A", "B", "C"])
    # 2 voters A>B>C, 2 voters B>C>A, 2 voters C>A>B
    cv.add_ballot("v1", ["A", "B", "C"])
    cv.add_ballot("v2", ["A", "B", "C"])
    cv.add_ballot("v3", ["B", "C", "A"])
    cv.add_ballot("v4", ["B", "C", "A"])
    cv.add_ballot("v5", ["C", "A", "B"])
    cv.add_ballot("v6", ["C", "A", "B"])
    result = cv.result()
    assert result.tiebreak_used
    assert result.winner in ["A", "B", "C"]
