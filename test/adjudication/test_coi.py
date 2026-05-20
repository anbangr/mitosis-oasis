"""Conflict-of-Interest recusal helper tests (Feature 2, Phase 1).

These tests verify the ``is_conflicted`` helper in
``oasis.adjudication.coi``.  They MUST be red before the implementation
is written (TDD invariant).
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from oasis.governance.schema import create_governance_tables
from oasis.adjudication.coi import is_conflicted


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------


def _seed_agent_registry(db_path: Path) -> None:
    """Seed agent_registry with agents owned by different human principals."""
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA foreign_keys = ON")
    agents = [
        # Agent1 owned by Adj1
        ("did:key:zagent1", "producer", "Agent 1", "did:key:zadj1"),
        # Agent2 owned by Adj2
        ("did:key:zagent2", "producer", "Agent 2", "did:key:zadj2"),
        # Agent3 owned by Adj1 (same owner as Agent1)
        ("did:key:zagent3", "producer", "Agent 3", "did:key:zadj1"),
        # Agent4 with no human_principal
        ("did:key:zagent4", "producer", "Agent 4", None),
    ]
    for agent_did, agent_type, display_name, human_principal in agents:
        conn.execute(
            "INSERT OR IGNORE INTO agent_registry "
            "(agent_did, agent_type, display_name, human_principal) "
            "VALUES (?, ?, ?, ?)",
            (agent_did, agent_type, display_name, human_principal),
        )
    conn.commit()
    conn.close()


@pytest.fixture()
def gov_db(tmp_path: Path) -> Path:
    """Fresh governance DB with seeded agent_registry."""
    db_path = tmp_path / "gov.db"
    create_governance_tables(db_path)
    _seed_agent_registry(db_path)
    return db_path


# ---------------------------------------------------------------------------
# T1 — Adjudicator owning agent in mission is conflicted
# ---------------------------------------------------------------------------


def test_conflicted_when_adjudicator_owns_agent_in_mission(gov_db: Path) -> None:
    """T1: Adj1 owns Agent1; Agent1 is in mission-X → is_conflicted returns True."""
    result = is_conflicted(
        adjudicator_did="did:key:zadj1",
        mission_id="mission-X",
        agents_in_mission={"did:key:zagent1"},
        gov_db_path=str(gov_db),
    )
    assert result is True


# ---------------------------------------------------------------------------
# T2 — Adjudicator with no owned agent in mission is not conflicted
# ---------------------------------------------------------------------------


def test_not_conflicted_when_adjudicator_owns_no_agent_in_mission(gov_db: Path) -> None:
    """T2: Adj2 owns nothing in mission-X → is_conflicted returns False."""
    result = is_conflicted(
        adjudicator_did="did:key:zadj2",
        mission_id="mission-X",
        agents_in_mission={"did:key:zagent1"},
        gov_db_path=str(gov_db),
    )
    assert result is False


# ---------------------------------------------------------------------------
# T3 — Empty agents_in_mission short-circuits to False
# ---------------------------------------------------------------------------


def test_empty_agents_short_circuits(gov_db: Path) -> None:
    """T3: Empty agents_in_mission → False without touching the DB."""
    # Pass a non-existent DB path to prove no query is attempted.
    result = is_conflicted(
        adjudicator_did="did:key:zadj1",
        mission_id="mission-X",
        agents_in_mission=set(),
        gov_db_path="/nonexistent/path.db",
    )
    assert result is False


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


def test_agent_not_in_registry_returns_false(gov_db: Path) -> None:
    """Agent in mission that is absent from agent_registry → still False."""
    result = is_conflicted(
        adjudicator_did="did:key:zadj1",
        mission_id="mission-X",
        agents_in_mission={"did:key:unknown-agent"},
        gov_db_path=str(gov_db),
    )
    assert result is False


def test_any_match_semantics_multiple_agents(gov_db: Path) -> None:
    """Multiple agents in mission; only one owned by adjudicator → True."""
    result = is_conflicted(
        adjudicator_did="did:key:zadj1",
        mission_id="mission-X",
        agents_in_mission={"did:key:zagent2", "did:key:zagent1"},
        gov_db_path=str(gov_db),
    )
    assert result is True


def test_case_sensitivity_exact_match(gov_db: Path) -> None:
    """DID matching is case-sensitive; uppercase input must not match lowercase stored value."""
    # Registry stores lowercase did:key:zagent1
    result = is_conflicted(
        adjudicator_did="did:key:zAdj1",  # different case
        mission_id="mission-X",
        agents_in_mission={"did:key:zAgent1"},  # different case
        gov_db_path=str(gov_db),
    )
    # Because SQL matching is exact (no lowercasing), this should NOT match
    assert result is False
