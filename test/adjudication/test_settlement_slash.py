"""Tests for settlement interaction with sanctions (slash on failure)."""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from oasis.adjudication.sanctions import SanctionEngine
from oasis.config import PlatformConfig


def test_failed_task_slash(
    adjudication_db: Path, agents: list[dict], config: PlatformConfig
) -> None:
    """Failed task results in stake slash."""
    engine = SanctionEngine(config)
    agent_did = agents[0]["agent_did"]

    # Slash for task failure
    decision = engine.slash_stake(agent_did, 5.0, "task_failure", adjudication_db)
    assert decision.decision_type == "slash"

    # Verify stake was reduced
    conn = sqlite3.connect(str(adjudication_db))
    conn.row_factory = sqlite3.Row
    bal = conn.execute(
        "SELECT locked_stake FROM agent_balance WHERE agent_did = ?",
        (agent_did,),
    ).fetchone()
    conn.close()
    assert bal["locked_stake"] == pytest.approx(5.0)  # 10 - 5


def test_frozen_task_slash(
    adjudication_db: Path, agents: list[dict], config: PlatformConfig
) -> None:
    """Frozen agent gets slashed."""
    engine = SanctionEngine(config)
    agent_did = agents[0]["agent_did"]

    # Freeze first, then slash
    engine.freeze_agent(agent_did, "misbehaviour", adjudication_db)
    decision = engine.slash_stake(agent_did, 3.0, "frozen_slash", adjudication_db)
    assert decision.decision_type == "slash"

    # Verify slash applied even while frozen
    conn = sqlite3.connect(str(adjudication_db))
    conn.row_factory = sqlite3.Row
    bal = conn.execute(
        "SELECT locked_stake FROM agent_balance WHERE agent_did = ?",
        (agent_did,),
    ).fetchone()
    conn.close()
    assert bal["locked_stake"] == pytest.approx(7.0)  # 10 - 3
