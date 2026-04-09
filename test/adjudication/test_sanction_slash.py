"""Tests for SanctionEngine stake slashing."""
from __future__ import annotations

import sqlite3
from pathlib import Path

from oasis.adjudication.sanctions import SanctionEngine
from oasis.config import PlatformConfig


def test_stake_deducted(
    adjudication_db: Path, agents: list[dict], config: PlatformConfig
) -> None:
    """Slashing deducts from locked_stake."""
    engine = SanctionEngine(config)
    agent_did = agents[0]["agent_did"]

    # Starting locked_stake is 10.0 (from conftest)
    engine.slash_stake(agent_did, 3.0, "test slash", adjudication_db)

    conn = sqlite3.connect(str(adjudication_db))
    conn.row_factory = sqlite3.Row
    bal = conn.execute(
        "SELECT locked_stake, total_balance FROM agent_balance WHERE agent_did = ?",
        (agent_did,),
    ).fetchone()
    conn.close()

    assert bal["locked_stake"] == pytest.approx(7.0)
    assert bal["total_balance"] == pytest.approx(97.0)


def test_treasury_receives_slash_proceeds(
    adjudication_db: Path, agents: list[dict], config: PlatformConfig
) -> None:
    """Slash proceeds appear in treasury."""
    engine = SanctionEngine(config)
    agent_did = agents[0]["agent_did"]

    engine.slash_stake(agent_did, 5.0, "test slash", adjudication_db)

    conn = sqlite3.connect(str(adjudication_db))
    conn.row_factory = sqlite3.Row
    entry = conn.execute(
        "SELECT * FROM treasury WHERE entry_type = 'slash_proceeds' "
        "ORDER BY entry_id DESC LIMIT 1",
    ).fetchone()
    conn.close()

    assert entry is not None
    assert entry["amount"] == pytest.approx(5.0)
    assert entry["balance_after"] == pytest.approx(5.0)


def test_insufficient_stake_partial_slash(
    adjudication_db: Path, agents: list[dict], config: PlatformConfig
) -> None:
    """When slash > locked_stake, only available amount is taken."""
    engine = SanctionEngine(config)
    agent_did = agents[0]["agent_did"]

    # locked_stake is 10.0, try to slash 50.0
    engine.slash_stake(agent_did, 50.0, "big slash", adjudication_db)

    conn = sqlite3.connect(str(adjudication_db))
    conn.row_factory = sqlite3.Row
    bal = conn.execute(
        "SELECT locked_stake FROM agent_balance WHERE agent_did = ?",
        (agent_did,),
    ).fetchone()
    conn.close()

    assert bal["locked_stake"] == pytest.approx(0.0)


def test_sanction_history_recorded(
    adjudication_db: Path, agents: list[dict], config: PlatformConfig
) -> None:
    """Slash creates an adjudication_decision record retrievable via history."""
    engine = SanctionEngine(config)
    agent_did = agents[0]["agent_did"]

    engine.slash_stake(agent_did, 2.0, "recorded slash", adjudication_db)

    history = engine.get_sanction_history(agent_did, adjudication_db)
    assert len(history) >= 1
    assert history[0].decision_type == "slash"
    assert "recorded slash" in history[0].reason


# Use pytest.approx for float comparisons
import pytest  # noqa: E402
