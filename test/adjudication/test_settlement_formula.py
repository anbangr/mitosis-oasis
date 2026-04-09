"""Tests for the settlement formula — reputation multiplier ψ and treasury subsidy."""
from __future__ import annotations

import pytest

from oasis.adjudication.settlement import SettlementCalculator
from oasis.config import PlatformConfig


def test_psi_at_zero(config: PlatformConfig) -> None:
    """ψ(0) = 1 + 0.5 × (0 - 0.5) / 1.0 = 1 - 0.25 = 0.75."""
    calc = SettlementCalculator(config)
    psi = calc.reputation_multiplier(0.0)
    assert psi == pytest.approx(0.75)


def test_psi_at_neutral(config: PlatformConfig) -> None:
    """ψ(neutral=0.5) = 1 + 0.5 × (0.5 - 0.5) / 1.0 = 1.0."""
    calc = SettlementCalculator(config)
    psi = calc.reputation_multiplier(0.5)
    assert psi == pytest.approx(1.0)


def test_psi_at_max(config: PlatformConfig) -> None:
    """ψ(1.0) = 1 + 0.5 × (1.0 - 0.5) / 1.0 = 1.25."""
    calc = SettlementCalculator(config)
    psi = calc.reputation_multiplier(1.0)
    assert psi == pytest.approx(1.25)


def test_subsidy_for_high_psi(config: PlatformConfig) -> None:
    """Treasury subsidy covers the premium when ψ > 1.0."""
    calc = SettlementCalculator(config)
    # ψ = 1.25, base_reward = 100
    # subsidy = 100 × (1.25 - 1.0) = 25.0
    subsidy = calc.compute_treasury_subsidy(100.0, 1.25)
    assert subsidy == pytest.approx(25.0)

    # ψ = 1.0 → no subsidy
    subsidy_zero = calc.compute_treasury_subsidy(100.0, 1.0)
    assert subsidy_zero == pytest.approx(0.0)

    # ψ = 0.75 → no subsidy
    subsidy_low = calc.compute_treasury_subsidy(100.0, 0.75)
    assert subsidy_low == pytest.approx(0.0)
