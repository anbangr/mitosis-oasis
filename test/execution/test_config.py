"""Tests for PlatformConfig — defaults, overrides, validation."""
from __future__ import annotations

import pytest

from oasis.config import PlatformConfig


def test_default_config_valid() -> None:
    """Default PlatformConfig has expected values."""
    cfg = PlatformConfig()
    assert cfg.execution_mode == "synthetic"
    assert cfg.synthetic_quality == "mixed"
    assert cfg.synthetic_success_rate == 0.8
    assert cfg.synthetic_latency_ms == (50, 200)
    assert cfg.adjudication_llm_enabled is False
    assert cfg.protocol_fee_rate == 0.02
    assert cfg.insurance_fee_rate == 0.01
    assert cfg.reputation_alpha == 0.5
    assert cfg.reputation_neutral == 0.5
    assert cfg.freeze_threshold == 0.9
    assert cfg.coordination_threshold == 0.7
    assert cfg.sanction_floor == 0.1


def test_overrides_work() -> None:
    """PlatformConfig accepts overrides for all parameters."""
    cfg = PlatformConfig(
        execution_mode="llm",
        synthetic_quality="perfect",
        synthetic_success_rate=1.0,
        synthetic_latency_ms=(10, 50),
        adjudication_llm_enabled=True,
        freeze_threshold=0.95,
        coordination_threshold=0.8,
        sanction_floor=0.05,
        protocol_fee_rate=0.03,
        insurance_fee_rate=0.02,
        reputation_alpha=0.7,
        reputation_neutral=0.6,
    )
    assert cfg.execution_mode == "llm"
    assert cfg.synthetic_quality == "perfect"
    assert cfg.synthetic_success_rate == 1.0
    assert cfg.adjudication_llm_enabled is True
    assert cfg.protocol_fee_rate == 0.03


def test_invalid_mode_rejected() -> None:
    """PlatformConfig rejects invalid execution_mode."""
    with pytest.raises(ValueError, match="Invalid execution_mode"):
        PlatformConfig(execution_mode="invalid")  # type: ignore[arg-type]
