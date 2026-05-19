# =========== Copyright 2023 @ CAMEL-AI.org. All Rights Reserved. ===========
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
# =========== Copyright 2023 @ CAMEL-AI.org. All Rights Reserved. ===========
"""Tests for split α/λ reputation parameters in config, EMA, and settlement.

Covers:
  T1 — both knobs exposed with default 0.5
  T2 — λ change does not perturb ψ (settlement multiplier is α-only)
  T3 — α change does not perturb EMA (EMA is λ-only)
  T4 — legacy adjudication tests stay green (verified via conftest fixtures)
  Edge cases for _compute_ema boundary values and reputation_multiplier.
"""

from __future__ import annotations

import pytest

from oasis.adjudication.sanctions import SanctionEngine
from oasis.adjudication.settlement import SettlementCalculator
from oasis.config import PlatformConfig


# ---------------------------------------------------------------------------
# T1: Both knobs exposed with default 0.5
# ---------------------------------------------------------------------------


def test_default_reputation_alpha_is_0_5() -> None:
    """Default PlatformConfig().reputation_alpha == 0.5."""
    cfg = PlatformConfig()
    assert cfg.reputation_alpha == pytest.approx(0.5)


def test_default_reputation_lambda_is_0_5() -> None:
    """Default PlatformConfig().reputation_lambda == 0.5 (new field)."""
    cfg = PlatformConfig()
    assert cfg.reputation_lambda == pytest.approx(0.5)


def test_both_default_knobs_equal_0_5() -> None:
    """T1: both reputation_alpha and reputation_lambda default to 0.5."""
    cfg = PlatformConfig()
    assert cfg.reputation_alpha == pytest.approx(0.5)
    assert cfg.reputation_lambda == pytest.approx(0.5)


# ---------------------------------------------------------------------------
# T2: λ change does not perturb ψ (settlement multiplier uses α only)
# ---------------------------------------------------------------------------


def test_reputation_multiplier_uses_alpha_not_lambda() -> None:
    """T2: reputation_multiplier(0.0) == 0.75 with α=0.5 even when λ=0.9.

    ψ = 1 + α × (ρ − ρ_neutral) / ρ_max
      = 1 + 0.5 × (0.0 − 0.5) / 1.0
      = 1 − 0.25
      = 0.75
    """
    cfg = PlatformConfig(reputation_alpha=0.5, reputation_lambda=0.9)
    calc = SettlementCalculator(cfg)
    assert calc.reputation_multiplier(0.0) == pytest.approx(0.75)


def test_reputation_multiplier_at_max_reputation() -> None:
    """ρ=1.0 with α=0.5 → ψ=1.25 (upper boundary of spec range)."""
    cfg = PlatformConfig(reputation_alpha=0.5, reputation_lambda=0.9)
    calc = SettlementCalculator(cfg)
    assert calc.reputation_multiplier(1.0) == pytest.approx(1.25)


def test_reputation_multiplier_alpha_disabled() -> None:
    """ρ=0.0 with α=0.0 → ψ=1.0 (multiplier collapses to identity)."""
    cfg = PlatformConfig(reputation_alpha=0.0, reputation_lambda=0.5)
    calc = SettlementCalculator(cfg)
    assert calc.reputation_multiplier(0.0) == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# T3: α change does not perturb EMA (_compute_ema uses λ only)
# ---------------------------------------------------------------------------


def test_compute_ema_uses_lambda_not_alpha() -> None:
    """T3: _compute_ema(0.5, 1.0) == 0.55 with λ=0.9 even when α=0.1.

    new = λ × old + (1 − λ) × score
        = 0.9 × 0.5 + 0.1 × 1.0
        = 0.45 + 0.10
        = 0.55
    """
    cfg = PlatformConfig(reputation_alpha=0.1, reputation_lambda=0.9)
    engine = SanctionEngine(cfg)
    assert engine._compute_ema(0.5, 1.0) == pytest.approx(0.55)


def test_compute_ema_lambda_zero_returns_new_score() -> None:
    """λ=0 (no smoothing) → _compute_ema returns the new score exactly."""
    cfg = PlatformConfig(reputation_alpha=0.5, reputation_lambda=0.0)
    engine = SanctionEngine(cfg)
    assert engine._compute_ema(0.5, 1.0) == pytest.approx(1.0)


def test_compute_ema_lambda_one_returns_old_score() -> None:
    """λ=1 (no update) → _compute_ema returns the old value exactly."""
    cfg = PlatformConfig(reputation_alpha=0.5, reputation_lambda=1.0)
    engine = SanctionEngine(cfg)
    assert engine._compute_ema(0.5, 1.0) == pytest.approx(0.5)


def test_compute_ema_default_config_midpoint() -> None:
    """With default λ=0.5: _compute_ema(0.5, 1.0) == 0.75."""
    cfg = PlatformConfig()
    engine = SanctionEngine(cfg)
    assert engine._compute_ema(0.5, 1.0) == pytest.approx(0.75)


# ---------------------------------------------------------------------------
# T4: Independent separation — changing one knob does not affect the other
# ---------------------------------------------------------------------------


def test_changing_lambda_does_not_affect_psi() -> None:
    """T4 proxy: two configs with different λ produce the same ψ."""
    cfg_a = PlatformConfig(reputation_alpha=0.5, reputation_lambda=0.1)
    cfg_b = PlatformConfig(reputation_alpha=0.5, reputation_lambda=0.9)
    calc_a = SettlementCalculator(cfg_a)
    calc_b = SettlementCalculator(cfg_b)
    assert calc_a.reputation_multiplier(0.8) == pytest.approx(
        calc_b.reputation_multiplier(0.8)
    )


def test_changing_alpha_does_not_affect_ema() -> None:
    """T4 proxy: two configs with different α produce the same EMA result."""
    cfg_a = PlatformConfig(reputation_alpha=0.1, reputation_lambda=0.7)
    cfg_b = PlatformConfig(reputation_alpha=0.9, reputation_lambda=0.7)
    engine_a = SanctionEngine(cfg_a)
    engine_b = SanctionEngine(cfg_b)
    assert engine_a._compute_ema(0.4, 0.8) == pytest.approx(
        engine_b._compute_ema(0.4, 0.8)
    )
