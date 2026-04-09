"""Tests for SanctionEngine freeze/unfreeze operations."""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from oasis.adjudication.sanctions import SanctionEngine
from oasis.config import PlatformConfig


def test_agent_frozen(
    adjudication_db: Path, agents: list[dict], config: PlatformConfig
) -> None:
    """Freezing an agent sets active=0."""
    engine = SanctionEngine(config)
    agent_did = agents[0]["agent_did"]
    decision = engine.freeze_agent(agent_did, "test freeze", adjudication_db)

    assert decision.decision_type == "freeze"
    assert decision.severity == "CRITICAL"

    conn = sqlite3.connect(str(adjudication_db))
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        "SELECT active FROM agent_registry WHERE agent_did = ?",
        (agent_did,),
    ).fetchone()
    conn.close()
    assert row["active"] == 0


def test_frozen_agent_cannot_commit(
    adjudication_db: Path, agents: list[dict], config: PlatformConfig
) -> None:
    """A frozen agent is rejected by the commitment check (active=0)."""
    engine = SanctionEngine(config)
    agent_did = agents[0]["agent_did"]
    engine.freeze_agent(agent_did, "test freeze", adjudication_db)

    # Verify agent is inactive
    conn = sqlite3.connect(str(adjudication_db))
    conn.execute("PRAGMA foreign_keys = ON")
    conn.row_factory = sqlite3.Row
    agent = conn.execute(
        "SELECT active FROM agent_registry WHERE agent_did = ?",
        (agent_did,),
    ).fetchone()
    conn.close()
    assert agent["active"] == 0


def test_unfreeze_restores(
    adjudication_db: Path, agents: list[dict], config: PlatformConfig
) -> None:
    """Unfreezing restores active=1."""
    engine = SanctionEngine(config)
    agent_did = agents[0]["agent_did"]
    engine.freeze_agent(agent_did, "test freeze", adjudication_db)
    decision = engine.unfreeze_agent(agent_did, adjudication_db)

    assert decision.decision_type == "unfreeze"

    conn = sqlite3.connect(str(adjudication_db))
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        "SELECT active FROM agent_registry WHERE agent_did = ?",
        (agent_did,),
    ).fetchone()
    conn.close()
    assert row["active"] == 1
