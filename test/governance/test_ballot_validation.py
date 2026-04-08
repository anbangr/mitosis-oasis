"""Ballot validation tests — 5 tests."""
import pytest

from oasis.governance.voting import validate_ballot, CopelandVoting


CANDIDATES = ["A", "B", "C"]


def test_complete_ranking_accepted():
    ok, reason = validate_ballot(["A", "B", "C"], CANDIDATES)
    assert ok
    assert reason == ""


def test_incomplete_ranking_rejected():
    ok, reason = validate_ballot(["A", "B"], CANDIDATES)
    assert not ok
    assert "Incomplete" in reason


def test_duplicates_rejected():
    ok, reason = validate_ballot(["A", "A", "C"], CANDIDATES)
    assert not ok
    assert "Duplicate" in reason


def test_unknown_candidate_rejected():
    ok, reason = validate_ballot(["A", "B", "X"], CANDIDATES)
    assert not ok
    assert "Unknown" in reason


def test_empty_ranking_rejected():
    ok, reason = validate_ballot([], CANDIDATES)
    assert not ok
    assert "Empty" in reason
