"""Tests for Treasury accounting operations."""
from __future__ import annotations

from pathlib import Path

import pytest

from oasis.adjudication.treasury import Treasury


def test_fees_recorded(adjudication_db: Path) -> None:
    """Protocol and insurance fees are recorded correctly."""
    treasury = Treasury(adjudication_db)

    entry = treasury.record_fee("task-001", "protocol_fee", 4.0)
    assert entry.entry_type == "protocol_fee"
    assert entry.amount == pytest.approx(4.0)
    assert entry.balance_after == pytest.approx(4.0)

    entry2 = treasury.record_fee("task-001", "insurance_fee", 2.0)
    assert entry2.entry_type == "insurance_fee"
    assert entry2.balance_after == pytest.approx(6.0)


def test_slash_recorded(adjudication_db: Path) -> None:
    """Slash proceeds are recorded with correct balance."""
    treasury = Treasury(adjudication_db)
    entry = treasury.record_slash("did:test:agent1", 10.0)

    assert entry.entry_type == "slash_proceeds"
    assert entry.amount == pytest.approx(10.0)
    assert entry.balance_after == pytest.approx(10.0)


def test_subsidy_recorded(adjudication_db: Path) -> None:
    """Subsidy outflow is recorded as negative amount."""
    treasury = Treasury(adjudication_db)
    # Seed some inflow first
    treasury.record_fee("task-001", "protocol_fee", 50.0)

    entry = treasury.record_subsidy("task-001", "did:test:agent1", 10.0)
    assert entry.entry_type == "reputation_subsidy"
    assert entry.amount == pytest.approx(-10.0)
    assert entry.balance_after == pytest.approx(40.0)  # 50 - 10


def test_balance_equals_inflows_minus_outflows(adjudication_db: Path) -> None:
    """Balance = sum of inflows - sum of outflows."""
    treasury = Treasury(adjudication_db)

    treasury.record_fee("t1", "protocol_fee", 100.0)
    treasury.record_fee("t1", "insurance_fee", 50.0)
    treasury.record_slash("did:slash:agent", 20.0)
    treasury.record_subsidy("t1", "did:sub:agent", 30.0)

    balance = treasury.get_balance()
    # 100 + 50 + 20 - 30 = 140
    assert balance == pytest.approx(140.0)

    summary = treasury.get_summary()
    assert summary.net_balance == pytest.approx(140.0)
    assert "protocol_fee" in summary.inflows
    assert "insurance_fee" in summary.inflows
    assert "slash_proceeds" in summary.inflows
    assert "reputation_subsidy" in summary.outflows
