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
"""ADJ-111 — Watchdog anomaly detection.

This test verifies that ``scan_anomalies`` and ``should_system_freeze``
expose the behaviour required by the v0.97 spec §2.4.  It MUST be red
before the implementation is written (TDD invariant).
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from oasis.adjudication.schema import create_adjudication_tables
from oasis.adjudication.watchdog import (
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
    return db_path


# ---------------------------------------------------------------------------
# T1 — Calibration mode below floor
# ---------------------------------------------------------------------------


def test_calibration_mode_below_floor(adj_db: Path) -> None:
    """T1: 5 adjudicators registered; only 3 decisions total → calibrating."""
    for i in range(5):
        adj_did = f"did:key:zAdj{i}"
        _seed_adjudicator(adj_db, adj_did)

    # Only 3 decisions total — below CALIBRATION_FLOOR (10)
    _insert_decision(
        adj_db,
        decision_id="d-001",
        agent_did="did:key:zAgent1",
        decision_type="approve",
        issued_by_did="did:key:zAdj0",
    )
    _insert_decision(
        adj_db,
        decision_id="d-002",
        agent_did="did:key:zAgent1",
        decision_type="approve",
        issued_by_did="did:key:zAdj1",
    )
    _insert_decision(
        adj_db,
        decision_id="d-003",
        agent_did="did:key:zAgent1",
        decision_type="reject",
        issued_by_did="did:key:zAdj2",
    )

    result = scan_anomalies(
        db_path=str(adj_db),
        window_days=30,
        zscore_threshold=2.0,
    )

    assert result["calibrating"] is True
    assert result["anomalies"] == []


# ---------------------------------------------------------------------------
# T2 — Outlier with 100% approval flagged among 50% peers
# ---------------------------------------------------------------------------


def test_outlier_100_percent_approval_flagged(adj_db: Path) -> None:
    """T2: Adj0 has 10 approved/0 rejected; Adj1-4 each have 5 approved/5 rejected.

    Adj0 should be flagged with ``approval_rate_deviation``; Adj1-4 are not.
    """
    for i in range(5):
        adj_did = f"did:key:zAdj{i}"
        _seed_adjudicator(adj_db, adj_did)

    # Adj0: 10 approve, 0 reject → 100% approval rate
    for idx in range(10):
        _insert_decision(
            adj_db,
            decision_id=f"d-adj0-{idx}",
            agent_did="did:key:zAgent1",
            decision_type="approve",
            issued_by_did="did:key:zAdj0",
        )

    # Adj1-4: 5 approve, 5 reject each → 50% approval rate
    for i in range(1, 5):
        adj_did = f"did:key:zAdj{i}"
        for idx in range(5):
            _insert_decision(
                adj_db,
                decision_id=f"d-{i}-app-{idx}",
                agent_did="did:key:zAgent1",
                decision_type="approve",
                issued_by_did=adj_did,
            )
            _insert_decision(
                adj_db,
                decision_id=f"d-{i}-rej-{idx}",
                agent_did="did:key:zAgent1",
                decision_type="reject",
                issued_by_did=adj_did,
            )

    result = scan_anomalies(
        db_path=str(adj_db),
        window_days=30,
        zscore_threshold=2.0,
    )

    assert result["calibrating"] is False
    anomalies = result["anomalies"]
    flagged_dids = {a["adjudicator_did"] for a in anomalies}
    assert "did:key:zAdj0" in flagged_dids
    for i in range(1, 5):
        assert f"did:key:zAdj{i}" not in flagged_dids

    # Verify Adj0 anomaly details
    adj0_anomalies = [a for a in anomalies if a["adjudicator_did"] == "did:key:zAdj0"]
    assert any(a["anomaly_type"] == "approval_rate_deviation" for a in adj0_anomalies)


# ---------------------------------------------------------------------------
# T3 — should_system_freeze triggers at ≥anomaly_threshold
# ---------------------------------------------------------------------------


def test_should_system_freeze_triggers_at_threshold(adj_db: Path) -> None:
    """T3: 2 watchdog_anomaly rows for Adj0 within window → True."""
    _seed_adjudicator(adj_db, "did:key:zAdj0")

    conn = sqlite3.connect(str(adj_db))
    conn.execute("PRAGMA foreign_keys = ON")
    for i in range(2):
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
        anomaly_threshold=2,
        window_days=30,
    )

    assert result is True


# ---------------------------------------------------------------------------
# T4 — should_system_freeze does not trigger below threshold
# ---------------------------------------------------------------------------


def test_should_system_freeze_does_not_trigger_below_threshold(adj_db: Path) -> None:
    """T4: 1 watchdog_anomaly row for Adj0 → False."""
    _seed_adjudicator(adj_db, "did:key:zAdj0")

    conn = sqlite3.connect(str(adj_db))
    conn.execute("PRAGMA foreign_keys = ON")
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
        anomaly_threshold=2,
        window_days=30,
    )

    assert result is False


# ---------------------------------------------------------------------------
# T5 — All-equal rates produce no outliers
# ---------------------------------------------------------------------------


def test_all_equal_rates_no_outliers(adj_db: Path) -> None:
    """T5: 5 adjudicators all with 50% approval → empty anomalies (stdev=0)."""
    for i in range(5):
        adj_did = f"did:key:zAdj{i}"
        _seed_adjudicator(adj_db, adj_did)

    # Each adjudicator: 5 approve, 5 reject → identical 50% rate
    for i in range(5):
        adj_did = f"did:key:zAdj{i}"
        for idx in range(5):
            _insert_decision(
                adj_db,
                decision_id=f"d-{i}-app-{idx}",
                agent_did="did:key:zAgent1",
                decision_type="approve",
                issued_by_did=adj_did,
            )
            _insert_decision(
                adj_db,
                decision_id=f"d-{i}-rej-{idx}",
                agent_did="did:key:zAgent1",
                decision_type="reject",
                issued_by_did=adj_did,
            )

    result = scan_anomalies(
        db_path=str(adj_db),
        window_days=30,
        zscore_threshold=2.0,
    )

    assert result["calibrating"] is False
    assert result["anomalies"] == []
