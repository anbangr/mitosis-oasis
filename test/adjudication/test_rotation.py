"""Rotation policy helper tests (Feature 3, Phase 1).

These tests verify the ``last_n_decisions`` and ``enforce_rotation`` helpers
in ``oasis.adjudication.rotation``.  They MUST be red before the
implementation is written (TDD invariant).
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from oasis.adjudication.schema import create_adjudication_tables
from oasis.adjudication.rotation import (
    enforce_rotation,
    last_n_decisions,
)


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------


def _seed_agents(db_path: Path) -> None:
    """Seed agent_registry so adjudication_decision FK does not fail."""
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA foreign_keys = ON")
    for i in range(1, 6):
        conn.execute(
            "INSERT OR IGNORE INTO agent_registry "
            "(agent_did, agent_type, display_name) VALUES (?, 'producer', ?)",
            (f"did:key:zagent{i}", f"Agent {i}"),
        )
    conn.commit()
    conn.close()


def _seed_decisions(
    db_path: Path,
    decisions: list[tuple[str, str, str]],
) -> None:
    """Insert adjudication_decision rows.

    Each tuple is (decision_type, issued_by_did, agent_did).
    created_at is staggered so ordering is deterministic.
    """
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA foreign_keys = ON")
    for idx, (decision_type, issued_by_did, agent_did) in enumerate(decisions):
        conn.execute(
            "INSERT INTO adjudication_decision "
            "(decision_id, agent_did, decision_type, severity, reason, "
            "layer1_result, issued_by_did, created_at) "
            "VALUES (?, ?, ?, 'INFO', 'test reason', 'test', ?, "
            "datetime('now', '-{} seconds'))".format(idx),
            (
                f"dec-{idx:04d}",
                agent_did,
                decision_type,
                issued_by_did,
            ),
        )
    conn.commit()
    conn.close()


@pytest.fixture()
def adj_db(tmp_path: Path) -> Path:
    """Fresh adjudication DB with schema and seeded agents."""
    db_path = tmp_path / "adj.db"
    create_adjudication_tables(db_path)
    _seed_agents(db_path)
    return db_path


# ---------------------------------------------------------------------------
# T1 — last_n_decisions returns correct count
# ---------------------------------------------------------------------------


def test_last_n_decisions_returns_correct_count(adj_db: Path) -> None:
    """T1: 5 decisions seeded for Adj1; last_n_decisions(n=3) returns 3."""
    decisions = [
        ("freeze", "did:key:zAdj1", "did:key:zagent1"),
        ("freeze", "did:key:zAdj1", "did:key:zagent2"),
        ("freeze", "did:key:zAdj1", "did:key:zagent3"),
        ("freeze", "did:key:zAdj1", "did:key:zagent4"),
        ("freeze", "did:key:zAdj1", "did:key:zagent5"),
    ]
    _seed_decisions(adj_db, decisions)

    result = last_n_decisions(
        adjudicator_did="did:key:zAdj1",
        n=3,
        db_path=str(adj_db),
    )
    assert len(result) == 3


# ---------------------------------------------------------------------------
# T2 — Third consecutive same-adjudicator decision blocked
# ---------------------------------------------------------------------------


def test_third_consecutive_same_adjudicator_blocked(adj_db: Path) -> None:
    """T2: Adj1 has 2 consecutive freezes; max_consecutive=2 → blocked."""
    decisions = [
        ("freeze", "did:key:zAdj1", "did:key:zagent1"),
        ("freeze", "did:key:zAdj1", "did:key:zagent2"),
    ]
    _seed_decisions(adj_db, decisions)

    result = enforce_rotation(
        adjudicator_did="did:key:zAdj1",
        decision_type="freeze",
        max_consecutive=2,
        db_path=str(adj_db),
    )
    assert result.allowed is False
    assert "rotation" in result.reason.lower()


# ---------------------------------------------------------------------------
# T3 — First two consecutive decisions allowed
# ---------------------------------------------------------------------------


def test_first_two_consecutive_allowed(adj_db: Path) -> None:
    """T3: Adj1 has 1 freeze; max_consecutive=2 → allowed."""
    decisions = [
        ("freeze", "did:key:zAdj1", "did:key:zagent1"),
    ]
    _seed_decisions(adj_db, decisions)

    result = enforce_rotation(
        adjudicator_did="did:key:zAdj1",
        decision_type="freeze",
        max_consecutive=2,
        db_path=str(adj_db),
    )
    assert result.allowed is True


# ---------------------------------------------------------------------------
# T4 — Different adjudicator's intervening decision resets streak
# ---------------------------------------------------------------------------


def test_intervening_different_adjudicator_resets_streak(adj_db: Path) -> None:
    """T4: 2 freezes by Adj1 then 1 freeze by Adj2 → Adj1 allowed."""
    decisions = [
        ("freeze", "did:key:zAdj1", "did:key:zagent1"),
        ("freeze", "did:key:zAdj1", "did:key:zagent2"),
        ("freeze", "did:key:zAdj2", "did:key:zagent3"),
    ]
    _seed_decisions(adj_db, decisions)

    result = enforce_rotation(
        adjudicator_did="did:key:zAdj1",
        decision_type="freeze",
        max_consecutive=2,
        db_path=str(adj_db),
    )
    assert result.allowed is True


# ---------------------------------------------------------------------------
# T5 — Different decision_type does not pollute the streak
# ---------------------------------------------------------------------------


def test_different_decision_type_does_not_pollute(adj_db: Path) -> None:
    """T5: 2 slashes by Adj1, 0 freezes → freeze call is allowed."""
    decisions = [
        ("slash", "did:key:zAdj1", "did:key:zagent1"),
        ("slash", "did:key:zAdj1", "did:key:zagent2"),
    ]
    _seed_decisions(adj_db, decisions)

    result = enforce_rotation(
        adjudicator_did="did:key:zAdj1",
        decision_type="freeze",
        max_consecutive=2,
        db_path=str(adj_db),
    )
    assert result.allowed is True


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


def test_empty_table_returns_allowed(adj_db: Path) -> None:
    """Empty adjudication_decision → enforce_rotation returns allowed=True."""
    result = enforce_rotation(
        adjudicator_did="did:key:zAdj1",
        decision_type="freeze",
        max_consecutive=2,
        db_path=str(adj_db),
    )
    assert result.allowed is True


def test_fewer_than_max_consecutive_returns_allowed(adj_db: Path) -> None:
    """Only 1 freeze exists; max_consecutive=3 → allowed."""
    decisions = [
        ("freeze", "did:key:zAdj1", "did:key:zagent1"),
    ]
    _seed_decisions(adj_db, decisions)

    result = enforce_rotation(
        adjudicator_did="did:key:zAdj1",
        decision_type="freeze",
        max_consecutive=3,
        db_path=str(adj_db),
    )
    assert result.allowed is True


def test_max_consecutive_one_blocks_immediately(adj_db: Path) -> None:
    """max_consecutive=1: one existing freeze blocks the next same-type freeze."""
    decisions = [
        ("freeze", "did:key:zAdj1", "did:key:zagent1"),
    ]
    _seed_decisions(adj_db, decisions)

    result = enforce_rotation(
        adjudicator_did="did:key:zAdj1",
        decision_type="freeze",
        max_consecutive=1,
        db_path=str(adj_db),
    )
    assert result.allowed is False
    assert "rotation" in result.reason.lower()


def test_max_consecutive_zero_undefined_returns_allowed(adj_db: Path) -> None:
    """max_consecutive=0 is undefined; spec says trivially True (no rows to check)."""
    decisions = [
        ("freeze", "did:key:zAdj1", "did:key:zagent1"),
    ]
    _seed_decisions(adj_db, decisions)

    result = enforce_rotation(
        adjudicator_did="did:key:zAdj1",
        decision_type="freeze",
        max_consecutive=0,
        db_path=str(adj_db),
    )
    assert result.allowed is True


def test_last_n_decisions_with_decision_type_filter(adj_db: Path) -> None:
    """last_n_decisions respects decision_type when provided."""
    decisions = [
        ("freeze", "did:key:zAdj1", "did:key:zagent1"),
        ("slash", "did:key:zAdj1", "did:key:zagent2"),
        ("freeze", "did:key:zAdj1", "did:key:zagent3"),
    ]
    _seed_decisions(adj_db, decisions)

    result = last_n_decisions(
        adjudicator_did="did:key:zAdj1",
        n=5,
        db_path=str(adj_db),
        decision_type="freeze",
    )
    assert len(result) == 2
    for row in result:
        assert row["decision_type"] == "freeze"


def test_last_n_decisions_returns_rows_with_issued_by_did(adj_db: Path) -> None:
    """last_n_decisions returns dict rows containing issued_by_did."""
    decisions = [
        ("freeze", "did:key:zAdj1", "did:key:zagent1"),
    ]
    _seed_decisions(adj_db, decisions)

    result = last_n_decisions(
        adjudicator_did="did:key:zAdj1",
        n=1,
        db_path=str(adj_db),
    )
    assert len(result) == 1
    assert result[0]["issued_by_did"] == "did:key:zAdj1"
