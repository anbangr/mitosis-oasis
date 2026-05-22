"""anchor_publisher commits one Merkle root per τ_anchor interval over
un-anchored event_log rows."""

from __future__ import annotations

import json
import sqlite3

import pytest

from oasis.adjudication.anchor_publisher import publish_anchor
from oasis.observatory.schema import create_observatory_tables


@pytest.fixture
def obs_db(tmp_path):
    p = tmp_path / "obs.db"
    create_observatory_tables(str(p))
    return str(p)


def _seed_events(db: str, n: int, anchored: bool = False):
    conn = sqlite3.connect(db)
    for i in range(n):
        anchor_id = f"anchor-old-{i}" if anchored else None
        conn.execute(
            "INSERT INTO event_log "
            "(event_id, event_type, timestamp, payload, sequence_number, anchor_id) "
            "VALUES (?, 'TEST', ?, ?, ?, ?)",
            (f"e{i}", float(i), json.dumps({"i": i}), i + 1, anchor_id),
        )
    conn.commit()
    conn.close()


def test_publish_anchor_with_no_pending_events_is_noop(obs_db):
    result = publish_anchor(db_path=obs_db, batch_max_size=1000)
    assert result is None  # nothing to anchor


def test_publish_anchor_creates_one_row(obs_db):
    _seed_events(obs_db, n=50)
    anchor = publish_anchor(db_path=obs_db, batch_max_size=1000)
    assert anchor is not None
    assert anchor["event_count"] == 50
    assert anchor["batch_start_seq"] == 1
    assert anchor["batch_end_seq"] == 50

    conn = sqlite3.connect(obs_db)
    rows = conn.execute("SELECT * FROM on_chain_anchor").fetchall()
    assert len(rows) == 1


def test_publish_anchor_marks_event_rows(obs_db):
    _seed_events(obs_db, n=50)
    anchor = publish_anchor(db_path=obs_db, batch_max_size=1000)
    conn = sqlite3.connect(obs_db)
    cnt = conn.execute(
        "SELECT COUNT(*) FROM event_log WHERE anchor_id = ?",
        (anchor["anchor_id"],),
    ).fetchone()[0]
    assert cnt == 50


def test_publish_anchor_respects_batch_max_size(obs_db):
    _seed_events(obs_db, n=2500)
    anchor = publish_anchor(db_path=obs_db, batch_max_size=1000)
    assert anchor["event_count"] == 1000
    assert anchor["batch_end_seq"] == 1000
    # Second call picks up the remaining
    anchor2 = publish_anchor(db_path=obs_db, batch_max_size=1000)
    assert anchor2["event_count"] == 1000
    assert anchor2["batch_start_seq"] == 1001
    anchor3 = publish_anchor(db_path=obs_db, batch_max_size=1000)
    assert anchor3["event_count"] == 500
    assert anchor3["batch_start_seq"] == 2001
    assert anchor3["batch_end_seq"] == 2500


def test_publish_anchor_empty_payload_fallback_to_canonical(obs_db):
    """Malformed/empty payloads fall back to canonical `{}` before Merkle hashing."""
    conn = sqlite3.connect(obs_db)
    conn.execute(
        "INSERT INTO event_log "
        "(event_id, event_type, timestamp, payload, sequence_number) "
        "VALUES (?, 'TEST', ?, ?, ?)",
        ("e-empty", 0.0, None, 1),
    )
    conn.execute(
        "INSERT INTO event_log "
        "(event_id, event_type, timestamp, payload, sequence_number) "
        "VALUES (?, 'TEST', ?, ?, ?)",
        ("e-malformed", 1.0, "not-json{{", 2),
    )
    conn.commit()
    conn.close()

    anchor = publish_anchor(db_path=obs_db, batch_max_size=1000)
    assert anchor is not None
    assert anchor["event_count"] == 2
    # Should succeed without raising — the Merkle root is computed over canonical payloads
    assert anchor["merkle_root_hex"] is not None
    assert len(anchor["merkle_root_hex"]) == 64  # 32 bytes as hex
