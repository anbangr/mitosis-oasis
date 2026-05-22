"""Spec exec §7.9: at Mission boundary, verify off-chain event_log vs
on-chain anchor rows. Divergence suspends the mission."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from oasis.adjudication.anchor_publisher import publish_anchor
from oasis.adjudication.reconciliation import reconcile_mission
from oasis.observatory.schema import create_observatory_tables


@pytest.fixture
def obs_db(tmp_path):
    p = tmp_path / "obs.db"
    create_observatory_tables(str(p))
    return str(p)


def _seed_mission_events(db: str, mission_id: str, n: int, start_seq: int = 1):
    conn = sqlite3.connect(db)
    for i in range(n):
        conn.execute(
            "INSERT INTO event_log "
            "(event_id, event_type, timestamp, payload, sequence_number, "
            "mission_id) "
            "VALUES (?, 'TEST', ?, ?, ?, ?)",
            (f"e-{mission_id}-{i}", float(i),
             json.dumps({"mission": mission_id, "i": i}, sort_keys=True),
             start_seq + i, mission_id),
        )
    conn.commit()
    conn.close()


def test_clean_mission_reconciles(obs_db):
    """Setup: insert event_log + mission_id col; create anchor; reconcile."""
    # event_log needs a mission_id column for this test; assume schema migration ran.
    _seed_mission_events(obs_db, "mission-A", n=10)
    publish_anchor(db_path=obs_db, batch_max_size=100, mission_id="mission-A")

    result = reconcile_mission(mission_id="mission-A", db_path=obs_db)
    assert result.status == "PASS"
    assert result.divergence_count == 0


def test_mission_with_unanchored_events_diverges(obs_db):
    _seed_mission_events(obs_db, "mission-B", n=10)
    publish_anchor(db_path=obs_db, batch_max_size=5, mission_id="mission-B")
    # Now 5 anchored + 5 unanchored

    result = reconcile_mission(mission_id="mission-B", db_path=obs_db)
    assert result.status == "DIVERGED"
    assert result.divergence_count == 5


def test_mission_with_tampered_payload_diverges(obs_db):
    _seed_mission_events(obs_db, "mission-C", n=5)
    anchor = publish_anchor(db_path=obs_db, batch_max_size=100,
                             mission_id="mission-C")

    # Tamper with one event payload AFTER anchoring
    conn = sqlite3.connect(obs_db)
    conn.execute(
        "UPDATE event_log SET payload = ? WHERE event_id = 'e-mission-C-2'",
        ('{"tampered": true}',),
    )
    conn.commit()
    conn.close()

    result = reconcile_mission(mission_id="mission-C", db_path=obs_db)
    assert result.status == "DIVERGED"
    assert "merkle" in result.reason.lower() or "hash" in result.reason.lower()


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


def test_empty_mission_passes(obs_db):
    """A mission with zero events should reconcile cleanly."""
    result = reconcile_mission(mission_id="mission-empty", db_path=obs_db)
    assert result.status == "PASS"
    assert result.divergence_count == 0


def test_missing_anchor_rows_diverges(obs_db):
    """Events exist for the mission but were never anchored → DIVERGED."""
    _seed_mission_events(obs_db, "mission-no-anchor", n=5)
    # Intentionally skip publish_anchor

    result = reconcile_mission(mission_id="mission-no-anchor", db_path=obs_db)
    assert result.status == "DIVERGED"
    assert result.divergence_count == 5


def test_malformed_payload_falls_back_to_empty_object(obs_db):
    """Malformed payloads are canonicalised to '{}' during recomputation,
    matching the publisher's behaviour, so reconciliation passes."""
    conn = sqlite3.connect(obs_db)
    for i in range(3):
        conn.execute(
            "INSERT INTO event_log "
            "(event_id, event_type, timestamp, payload, sequence_number, mission_id) "
            "VALUES (?, 'TEST', ?, ?, ?, ?)",
            (f"e-malformed-{i}", float(i),
             json.dumps({"i": i}, sort_keys=True),
             i + 1, "mission-malformed"),
        )
    # One malformed payload
    conn.execute(
        "INSERT INTO event_log "
        "(event_id, event_type, timestamp, payload, sequence_number, mission_id) "
        "VALUES (?, 'TEST', ?, ?, ?, ?)",
        ("e-malformed-bad", 3.0, "not-json{{{{", 4, "mission-malformed"),
    )
    conn.commit()
    conn.close()

    publish_anchor(db_path=obs_db, batch_max_size=100,
                   mission_id="mission-malformed")

    result = reconcile_mission(mission_id="mission-malformed", db_path=obs_db)
    assert result.status == "PASS"
    assert result.divergence_count == 0
