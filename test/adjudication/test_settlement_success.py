"""Tests for SettlementCalculator successful settlement flow."""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from oasis.adjudication.settlement import SettlementCalculator
from oasis.config import PlatformConfig


def test_full_settlement_computed(
    adjudication_db: Path, seeded_task: dict, config: PlatformConfig
) -> None:
    """Full settlement produces valid SettlementResult with all fields."""
    calc = SettlementCalculator(config)
    result = calc.settle_task(seeded_task["task_id"], adjudication_db)

    assert result.task_id == seeded_task["task_id"]
    assert result.agent_did == seeded_task["agent_did"]
    assert result.base_reward > 0
    assert result.final_reward > 0
    assert result.settlement_id.startswith("settle-")


def test_fees_deducted(
    adjudication_db: Path, seeded_task: dict, config: PlatformConfig
) -> None:
    """Protocol and insurance fees are correctly deducted from reward_basis."""
    calc = SettlementCalculator(config)
    result = calc.settle_task(seeded_task["task_id"], adjudication_db)

    # reward_basis = token_budget = 200.0
    # protocol_fee = 200 * 0.02 = 4.0
    # insurance_fee = 200 * 0.01 = 2.0
    # base_reward = 200 * (1 - 0.02 - 0.01) = 200 * 0.97 = 194.0
    assert result.protocol_fee == pytest.approx(4.0)
    assert result.insurance_fee == pytest.approx(2.0)
    assert result.base_reward == pytest.approx(194.0)


def test_reputation_multiplier_applied(
    adjudication_db: Path, seeded_task: dict, config: PlatformConfig
) -> None:
    """Reputation multiplier (ψ) is correctly computed and applied."""
    calc = SettlementCalculator(config)
    # Agent reputation = 0.5 = neutral → ψ = 1.0
    result = calc.settle_task(seeded_task["task_id"], adjudication_db)

    assert result.reputation_multiplier == pytest.approx(1.0)
    # With ψ = 1.0 and subsidy = 0, final_reward = base_reward
    assert result.final_reward == pytest.approx(result.base_reward)


def test_balance_updated(
    adjudication_db: Path, seeded_task: dict, config: PlatformConfig
) -> None:
    """Agent balance is updated after settlement."""
    # Get initial balance
    conn = sqlite3.connect(str(adjudication_db))
    conn.row_factory = sqlite3.Row
    initial = conn.execute(
        "SELECT total_balance, available_balance FROM agent_balance WHERE agent_did = ?",
        (seeded_task["agent_did"],),
    ).fetchone()
    conn.close()

    initial_total = initial["total_balance"]
    initial_available = initial["available_balance"]

    calc = SettlementCalculator(config)
    result = calc.settle_task(seeded_task["task_id"], adjudication_db)

    conn = sqlite3.connect(str(adjudication_db))
    conn.row_factory = sqlite3.Row
    after = conn.execute(
        "SELECT total_balance, available_balance FROM agent_balance WHERE agent_did = ?",
        (seeded_task["agent_did"],),
    ).fetchone()
    conn.close()

    assert after["total_balance"] == pytest.approx(initial_total + result.final_reward)
    assert after["available_balance"] == pytest.approx(initial_available + result.final_reward)
