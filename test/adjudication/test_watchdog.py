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
"""Watchdog anomaly detection unit tests (Feature 5, Phase 1).

These tests verify the internal helpers and edge cases for
``oasis.adjudication.watchdog``.  They MUST be red before the
implementation is written (TDD invariant).
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from oasis.adjudication.schema import create_adjudication_tables
from oasis.adjudication.watchdog import (
    CALIBRATION_FLOOR,
    _approval_rates,
    _freeze_lift_rates,
    _zscore_outliers,
    scan_anomalies,
    should_system_freeze,
)


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------


def _seed_adjudicator(db_path: Path, adjudicator_did: str) -> None:
    """Seed a single adjudicator into adjudicator_registry."""
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute(
        "INSERT OR IGNORE INTO adjudicator_registry "
        "(adjudicator_did, eth_address) VALUES (?, ?)",
        (adjudicator_did, adjudicator_did.replace(":", "")[-40:].lower()),
    )
    conn.commit()
    conn.close()


def _seed_agent(db_path: Path, agent_did: str) -> None:
    """Seed a single agent so adjudication_decision FK does not fail."""
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute(
        "INSERT OR IGNORE INTO agent_registry "
        "(agent_did, agent_type, display_name) VALUES (?, 'producer', ?)",
        (agent_did, agent_did),
    )
    conn.commit()
    conn.close()


def _insert_decision(
    db_path: Path,
    *,
    decision_id: str,
    agent_did: str,
    decision_type: str,
    issued_by_did: str,
    created_at_offset: str = "-1 days",
) -> None:
    """Insert an adjudication_decision row with a specific created_at offset."""
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute(
        "INSERT INTO adjudication_decision "
        "(decision_id, agent_did, decision_type, severity, reason, "
        "layer1_result, issued_by_did, created_at) "
        "VALUES (?, ?, ?, 'INFO', 'test reason', 'test', ?, "
        "datetime('now', ?))",
        (decision_id, agent_did, decision_type, issued_by_did, created_at_offset),
    )
    conn.commit()
    conn.close()


@pytest.fixture()
def adj_db(tmp_path: Path) -> Path:
    """Fresh adjudication DB with schema and seeded agents."""
    db_path = tmp_path / "adj.db"
    create_adjudication_tables(db_path)
    _seed_agent(db_path, "did:key:zAgent1")
    _seed_agent(db_path, "did:key:zAgent2")
    return db_path


# ---------------------------------------------------------------------------
# _approval_rates
# ---------------------------------------------------------------------------


def test_approval_rates_basic(adj_db: Path) -> None:
    """_approval_rates computes the ratio of (approve+unfreeze) / total."""
    _seed_adjudicator(adj_db, "did:key:zAdj0")
    _seed_adjudicator(adj_db, "did:key:zAdj1")

    # Adj0: 4 approve, 1 reject → 80% approval rate
    for idx in range(4):
        _insert_decision(
            adj_db,
            decision_id=f"d-a0-{idx}",
            agent_did="did:key:zAgent1",
            decision_type="approve",
            issued_by_did="did:key:zAdj0",
        )
    _insert_decision(
        adj_db,
        decision_id="d-a0-rej",
        agent_did="did:key:zAgent1",
        decision_type="reject",
        issued_by_did="did:key:zAdj0",
    )

    # Adj1: 2 approve, 2 unfreeze, 1 reject → 80% approval rate
    for idx in range(2):
        _insert_decision(
            adj_db,
            decision_id=f"d-a1-{idx}",
            agent_did="did:key:zAgent1",
            decision_type="approve",
            issued_by_did="did:key:zAdj1",
        )
    for idx in range(2):
        _insert_decision(
            adj_db,
            decision_id=f"d-a1-uf-{idx}",
            agent_did="did:key:zAgent1",
            decision_type="unfreeze",
            issued_by_did="did:key:zAdj1",
        )
    _insert_decision(
        adj_db,
        decision_id="d-a1-rej",
        agent_did="did:key:zAgent1",
        decision_type="reject",
        issued_by_did="did:key:zAdj1",
    )

    rates = _approval_rates(db_path=str(adj_db), window_days=30)

    assert rates["did:key:zAdj0"] == pytest.approx(0.8)
    assert rates["did:key:zAdj1"] == pytest.approx(0.8)


def test_approval_rates_excludes_outside_window(adj_db: Path) -> None:
    """Decisions older than window_days are excluded from _approval_rates."""
    _seed_adjudicator(adj_db, "did:key:zAdj0")

    # Inside window: 1 approve
    _insert_decision(
        adj_db,
        decision_id="d-in",
        agent_did="did:key:zAgent1",
        decision_type="approve",
        issued_by_did="did:key:zAdj0",
        created_at_offset="-5 days",
    )
    # Outside window: 1 reject
    _insert_decision(
        adj_db,
        decision_id="d-out",
        agent_did="did:key:zAgent1",
        decision_type="reject",
        issued_by_did="did:key:zAdj0",
        created_at_offset="-31 days",
    )

    rates = _approval_rates(db_path=str(adj_db), window_days=30)

    assert rates["did:key:zAdj0"] == pytest.approx(1.0)


def test_approval_rates_groups_by_issued_by_did(adj_db: Path) -> None:
    """_approval_rates groups by issued_by_did, never by agent_did."""
    _seed_adjudicator(adj_db, "did:key:zAdj0")

    # Same adjudicator, different agents
    _insert_decision(
        adj_db,
        decision_id="d-1",
        agent_did="did:key:zAgent1",
        decision_type="approve",
        issued_by_did="did:key:zAdj0",
    )
    _insert_decision(
        adj_db,
        decision_id="d-2",
        agent_did="did:key:zAgent2",
        decision_type="reject",
        issued_by_did="did:key:zAdj0",
    )

    rates = _approval_rates(db_path=str(adj_db), window_days=30)

    # Should be a single entry for Adj0, not split by agent
    assert len(rates) == 1
    assert rates["did:key:zAdj0"] == pytest.approx(0.5)


# ---------------------------------------------------------------------------
# _freeze_lift_rates
# ---------------------------------------------------------------------------


def test_freeze_lift_rates_basic(adj_db: Path) -> None:
    """_freeze_lift_rates computes unfreeze / freeze ratio."""
    _seed_adjudicator(adj_db, "did:key:zAdj0")

    # 2 freezes, 1 unfreeze → 50% lift rate
    for idx in range(2):
        _insert_decision(
            adj_db,
            decision_id=f"d-fr-{idx}",
            agent_did="did:key:zAgent1",
            decision_type="freeze",
            issued_by_did="did:key:zAdj0",
        )
    _insert_decision(
        adj_db,
        decision_id="d-uf",
        agent_did="did:key:zAgent1",
        decision_type="unfreeze",
        issued_by_did="did:key:zAdj0",
    )

    rates = _freeze_lift_rates(db_path=str(adj_db), window_days=30)

    assert rates["did:key:zAdj0"] == pytest.approx(0.5)


def test_freeze_lift_rates_zero_freezes_returns_zero(adj_db: Path) -> None:
    """Adjudicator with 0 freezes in window → _freeze_lift_rates returns 0.0."""
    _seed_adjudicator(adj_db, "did:key:zAdj0")

    # Only approve decisions, no freezes
    _insert_decision(
        adj_db,
        decision_id="d-app",
        agent_did="did:key:zAgent1",
        decision_type="approve",
        issued_by_did="did:key:zAdj0",
    )

    rates = _freeze_lift_rates(db_path=str(adj_db), window_days=30)

    assert rates["did:key:zAdj0"] == pytest.approx(0.0)


def test_freeze_lift_rates_no_unfreeze_returns_zero(adj_db: Path) -> None:
    """Adjudicator with freezes but no unfreezes → 0.0 lift rate."""
    _seed_adjudicator(adj_db, "did:key:zAdj0")

    _insert_decision(
        adj_db,
        decision_id="d-fr",
        agent_did="did:key:zAgent1",
        decision_type="freeze",
        issued_by_did="did:key:zAdj0",
    )

    rates = _freeze_lift_rates(db_path=str(adj_db), window_days=30)

    assert rates["did:key:zAdj0"] == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# _zscore_outliers
# ---------------------------------------------------------------------------


def test_zscore_outliers_detects_high_outlier() -> None:
    """A value significantly above the median is flagged."""
    rates = {
        "did:key:zAdj0": 1.0,   # outlier
        "did:key:zAdj1": 0.5,
        "did:key:zAdj2": 0.5,
        "did:key:zAdj3": 0.5,
        "did:key:zAdj4": 0.5,
    }
    outliers = _zscore_outliers(rates, threshold=2.0)

    assert "did:key:zAdj0" in outliers
    assert outliers["did:key:zAdj0"] > 2.0
    for i in range(1, 5):
        assert f"did:key:zAdj{i}" not in outliers


def test_zscore_outliers_detects_low_outlier() -> None:
    """A value significantly below the median is flagged."""
    rates = {
        "did:key:zAdj0": 0.0,   # outlier
        "did:key:zAdj1": 0.5,
        "did:key:zAdj2": 0.5,
        "did:key:zAdj3": 0.5,
        "did:key:zAdj4": 0.5,
    }
    outliers = _zscore_outliers(rates, threshold=2.0)

    assert "did:key:zAdj0" in outliers
    assert outliers["did:key:zAdj0"] < -2.0


def test_zscore_outliers_skips_when_stdev_zero() -> None:
    """All-equal rates → stdev=0 → no outliers (no division-by-zero)."""
    rates = {
        "did:key:zAdj0": 0.5,
        "did:key:zAdj1": 0.5,
        "did:key:zAdj2": 0.5,
    }
    outliers = _zscore_outliers(rates, threshold=2.0)

    assert outliers == {}


def test_zscore_outliers_single_adjudicator_no_outliers() -> None:
    """Only one adjudicator in population → no outliers (cannot z-score itself)."""
    rates = {"did:key:zAdj0": 1.0}
    outliers = _zscore_outliers(rates, threshold=2.0)

    assert outliers == {}


def test_zscore_outliers_two_adjudicators_extreme_difference() -> None:
    """Two adjudicators with extreme rates → both flagged if |z| ≥ threshold."""
    rates = {
        "did:key:zAdj0": 1.0,
        "did:key:zAdj1": 0.0,
    }
    outliers = _zscore_outliers(rates, threshold=1.0)

    assert "did:key:zAdj0" in outliers
    assert "did:key:zAdj1" in outliers


def test_zscore_outliers_below_threshold_not_flagged() -> None:
    """Values with |z| < threshold are not flagged."""
    rates = {
        "did:key:zAdj0": 0.6,
        "did:key:zAdj1": 0.5,
        "did:key:zAdj2": 0.4,
    }
    outliers = _zscore_outliers(rates, threshold=2.0)

    assert outliers == {}


# ---------------------------------------------------------------------------
# scan_anomalies — edge cases
# ---------------------------------------------------------------------------


def test_scan_anomalies_single_adjudicator_no_outliers(adj_db: Path) -> None:
    """Single adjudicator in population → no outliers."""
    _seed_adjudicator(adj_db, "did:key:zAdj0")

    for idx in range(CALIBRATION_FLOOR):
        _insert_decision(
            adj_db,
            decision_id=f"d-{idx}",
            agent_did="did:key:zAgent1",
            decision_type="approve",
            issued_by_did="did:key:zAdj0",
        )

    result = scan_anomalies(
        db_path=str(adj_db),
        window_days=30,
        zscore_threshold=2.0,
    )

    assert result["calibrating"] is False
    assert result["anomalies"] == []


def test_scan_anomalies_window_boundary_included(adj_db: Path) -> None:
    """A decision exactly window_days old is included (>= boundary)."""
    _seed_adjudicator(adj_db, "did:key:zAdj0")
    _seed_adjudicator(adj_db, "did:key:zAdj1")

    # Exactly 30 days old — should be included
    _insert_decision(
        adj_db,
        decision_id="d-boundary",
        agent_did="did:key:zAgent1",
        decision_type="approve",
        issued_by_did="did:key:zAdj0",
        created_at_offset="-30 days",
    )

    # Fill up to calibration floor with Adj1
    for idx in range(CALIBRATION_FLOOR - 1):
        _insert_decision(
            adj_db,
            decision_id=f"d-cal-{idx}",
            agent_did="did:key:zAgent1",
            decision_type="reject",
            issued_by_did="did:key:zAdj1",
        )

    rates = _approval_rates(db_path=str(adj_db), window_days=30)

    # The boundary decision should be counted
    assert "did:key:zAdj0" in rates
    assert rates["did:key:zAdj0"] == pytest.approx(1.0)


def test_scan_anomalies_double_scan_persists_twice(adj_db: Path) -> None:
    """Two successive scans without new decisions → both persist anomalies."""
    _seed_adjudicator(adj_db, "did:key:zAdj0")
    _seed_adjudicator(adj_db, "did:key:zAdj1")

    # Adj0: 10 approve, 0 reject → 100%
    for idx in range(10):
        _insert_decision(
            adj_db,
            decision_id=f"d-a0-{idx}",
            agent_did="did:key:zAgent1",
            decision_type="approve",
            issued_by_did="did:key:zAdj0",
        )

    # Adj1: 5 approve, 5 reject → 50%
    for idx in range(5):
        _insert_decision(
            adj_db,
            decision_id=f"d-a1-app-{idx}",
            agent_did="did:key:zAgent1",
            decision_type="approve",
            issued_by_did="did:key:zAdj1",
        )
        _insert_decision(
            adj_db,
            decision_id=f"d-a1-rej-{idx}",
            agent_did="did:key:zAgent1",
            decision_type="reject",
            issued_by_did="did:key:zAdj1",
        )

    scan_anomalies(db_path=str(adj_db), window_days=30, zscore_threshold=2.0)
    scan_anomalies(db_path=str(adj_db), window_days=30, zscore_threshold=2.0)

    conn = sqlite3.connect(str(adj_db))
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT COUNT(*) as cnt FROM watchdog_anomaly WHERE adjudicator_did = ?",
        ("did:key:zAdj0",),
    ).fetchall()
    conn.close()

    # Both scans persisted → 2 rows (idempotency is out of scope per spec)
    assert rows[0]["cnt"] == 2


def test_scan_anomalies_persists_to_watchdog_anomaly(adj_db: Path) -> None:
    """Detected anomalies are persisted to the watchdog_anomaly table."""
    _seed_adjudicator(adj_db, "did:key:zAdj0")
    _seed_adjudicator(adj_db, "did:key:zAdj1")

    # Adj0: 10 approve, 0 reject → outlier
    for idx in range(10):
        _insert_decision(
            adj_db,
            decision_id=f"d-a0-{idx}",
            agent_did="did:key:zAgent1",
            decision_type="approve",
            issued_by_did="did:key:zAdj0",
        )

    # Adj1: 5 approve, 5 reject → normal
    for idx in range(5):
        _insert_decision(
            adj_db,
            decision_id=f"d-a1-app-{idx}",
            agent_did="did:key:zAgent1",
            decision_type="approve",
            issued_by_did="did:key:zAdj1",
        )
        _insert_decision(
            adj_db,
            decision_id=f"d-a1-rej-{idx}",
            agent_did="did:key:zAgent1",
            decision_type="reject",
            issued_by_did="did:key:zAdj1",
        )

    result = scan_anomalies(
        db_path=str(adj_db),
        window_days=30,
        zscore_threshold=2.0,
    )

    assert len(result["anomalies"]) >= 1

    conn = sqlite3.connect(str(adj_db))
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT * FROM watchdog_anomaly WHERE adjudicator_did = ?",
        ("did:key:zAdj0",),
    ).fetchall()
    conn.close()

    assert len(rows) >= 1
    assert rows[0]["anomaly_type"] == "approval_rate_deviation"
    assert rows[0]["zscore"] > 2.0
    assert rows[0]["window_decisions"] == 10


def test_scan_anomalies_freeze_lift_rate_deviation(adj_db: Path) -> None:
    """Freeze/lift rate outliers are also detected and persisted."""
    _seed_adjudicator(adj_db, "did:key:zAdj0")
    _seed_adjudicator(adj_db, "did:key:zAdj1")

    # Adj0: 10 freezes, 0 unfreezes → 0% lift rate (outlier if others are high)
    for idx in range(10):
        _insert_decision(
            adj_db,
            decision_id=f"d-a0-fr-{idx}",
            agent_did="did:key:zAgent1",
            decision_type="freeze",
            issued_by_did="did:key:zAdj0",
        )

    # Adj1: 5 freezes, 5 unfreezes → 100% lift rate
    for idx in range(5):
        _insert_decision(
            adj_db,
            decision_id=f"d-a1-fr-{idx}",
            agent_did="did:key:zAgent1",
            decision_type="freeze",
            issued_by_did="did:key:zAdj1",
        )
        _insert_decision(
            adj_db,
            decision_id=f"d-a1-uf-{idx}",
            agent_did="did:key:zAgent1",
            decision_type="unfreeze",
            issued_by_did="did:key:zAdj1",
        )

    result = scan_anomalies(
        db_path=str(adj_db),
        window_days=30,
        zscore_threshold=2.0,
    )

    # At least one anomaly should be detected (either Adj0 or Adj1)
    assert len(result["anomalies"]) >= 1
    types = {a["anomaly_type"] for a in result["anomalies"]}
    assert "freeze_lift_rate_deviation" in types


# ---------------------------------------------------------------------------
# should_system_freeze — edge cases
# ---------------------------------------------------------------------------


def test_should_system_freeze_counts_only_within_window(adj_db: Path) -> None:
    """Anomalies outside the window are not counted."""
    _seed_adjudicator(adj_db, "did:key:zAdj0")

    conn = sqlite3.connect(str(adj_db))
    conn.execute("PRAGMA foreign_keys = ON")
    # Old anomaly (outside window)
    conn.execute(
        "INSERT INTO watchdog_anomaly "
        "(adjudicator_did, anomaly_type, zscore, window_decisions, detected_at) "
        "VALUES (?, 'approval_rate_deviation', 2.5, 10, datetime('now', '-31 days'))",
        ("did:key:zAdj0",),
    )
    # Recent anomaly (inside window)
    conn.execute(
        "INSERT INTO watchdog_anomaly "
        "(adjudicator_did, anomaly_type, zscore, window_decisions, detected_at) "
        "VALUES (?, 'approval_rate_deviation', 2.5, 10, datetime('now', '-1 days'))",
        ("did:key:zAdj0",),
    )
    conn.commit()
    conn.close()

    result = should_system_freeze(
        db_path=str(adj_db),
        adjudicator_did="did:key:zAdj0",
        anomaly_threshold=2,
        window_days=30,
    )

    assert result is False


def test_should_system_freeze_exactly_at_threshold(adj_db: Path) -> None:
    """Exactly anomaly_threshold rows → True (≥ threshold)."""
    _seed_adjudicator(adj_db, "did:key:zAdj0")

    conn = sqlite3.connect(str(adj_db))
    conn.execute("PRAGMA foreign_keys = ON")
    for i in range(3):
        conn.execute(
            "INSERT INTO watchdog_anomaly "
            "(adjudicator_did, anomaly_type, zscore, window_decisions) "
            "VALUES (?, 'approval_rate_deviation', 2.5, 10)",
            ("did:key:zAdj0",),
        )
    conn.commit()
    conn.close()

    result = should_system_freeze(
        db_path=str(adj_db),
        adjudicator_did="did:key:zAdj0",
        anomaly_threshold=3,
        window_days=30,
    )

    assert result is True


def test_should_system_freeze_zero_anomalies(adj_db: Path) -> None:
    """No anomalies for adjudicator → False."""
    _seed_adjudicator(adj_db, "did:key:zAdj0")

    result = should_system_freeze(
        db_path=str(adj_db),
        adjudicator_did="did:key:zAdj0",
        anomaly_threshold=1,
        window_days=30,
    )

    assert result is False
