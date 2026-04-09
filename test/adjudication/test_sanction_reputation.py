"""Tests for SanctionEngine reputation reduction (EMA update)."""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from oasis.adjudication.sanctions import SanctionEngine
from oasis.config import PlatformConfig


def test_ema_update_correct(
    adjudication_db: Path, agents: list[dict], config: PlatformConfig
) -> None:
    """EMA formula: new_rep = λ * old_rep + (1-λ) * performance_score."""
    engine = SanctionEngine(config)
    agent_did = agents[0]["agent_did"]
    # old_rep = 0.5, λ = 0.5, performance = 0.2
    # new_rep = 0.5 * 0.5 + 0.5 * 0.2 = 0.25 + 0.10 = 0.35
    engine.reduce_reputation(agent_did, 0.2, adjudication_db)

    conn = sqlite3.connect(str(adjudication_db))
    conn.row_factory = sqlite3.Row
    agent = conn.execute(
        "SELECT reputation_score FROM agent_registry WHERE agent_did = ?",
        (agent_did,),
    ).fetchone()
    conn.close()

    assert agent["reputation_score"] == pytest.approx(0.35)


def test_lambda_default(config: PlatformConfig) -> None:
    """Default λ (reputation_alpha) is 0.5."""
    assert config.reputation_alpha == pytest.approx(0.5)


def test_reputation_ledger_appended(
    adjudication_db: Path, agents: list[dict], config: PlatformConfig
) -> None:
    """Reputation reduction appends to reputation_ledger."""
    engine = SanctionEngine(config)
    agent_did = agents[0]["agent_did"]
    engine.reduce_reputation(agent_did, 0.3, adjudication_db)

    conn = sqlite3.connect(str(adjudication_db))
    conn.row_factory = sqlite3.Row
    entry = conn.execute(
        "SELECT * FROM reputation_ledger WHERE agent_did = ? "
        "ORDER BY entry_id DESC LIMIT 1",
        (agent_did,),
    ).fetchone()
    conn.close()

    assert entry is not None
    assert entry["old_score"] == pytest.approx(0.5)
    # new = 0.5 * 0.5 + 0.5 * 0.3 = 0.40
    assert entry["new_score"] == pytest.approx(0.40)
    assert entry["performance_score"] == pytest.approx(0.3)
    assert entry["lambda"] == pytest.approx(0.5)
