"""Spec exec §7, §9: off-chain logs anchored to on-chain Merkle roots
at checkpoint boundaries. Anchor must cover sequence ranges
contiguously with no gaps."""

import json
import sqlite3

import pytest

from oasis.adjudication.anchor_publisher import publish_anchor
from oasis.crypto import merkle
from oasis.observatory.schema import create_observatory_tables


@pytest.fixture
def obs_db(tmp_path):
    p = tmp_path / "obs.db"
    create_observatory_tables(str(p))
    return str(p)


def test_anchor_merkle_root_matches_recomputation(obs_db):
    """The persisted root MUST equal SHA-256 Merkle over the anchored events
    in sequence order."""
    conn = sqlite3.connect(obs_db)
    events = []
    for i in range(8):
        payload = json.dumps({"i": i}, sort_keys=True)
        conn.execute(
            "INSERT INTO event_log "
            "(event_id, event_type, timestamp, payload, sequence_number) "
            "VALUES (?, 'TEST', ?, ?, ?)",
            (f"e{i}", float(i), payload, i + 1),
        )
        events.append(payload)
    conn.commit()
    conn.close()

    anchor = publish_anchor(db_path=obs_db, batch_max_size=1000)
    leaves = [e.encode() for e in events]
    expected_root = merkle.build_root(leaves)
    assert anchor["merkle_root_hex"] == expected_root.hex()


def test_consecutive_anchors_have_no_seq_gap(obs_db):
    conn = sqlite3.connect(obs_db)
    for i in range(2500):
        conn.execute(
            "INSERT INTO event_log "
            "(event_id, event_type, timestamp, payload, sequence_number) "
            "VALUES (?, 'TEST', ?, ?, ?)",
            (f"e{i}", float(i), "{}", i + 1),
        )
    conn.commit()
    conn.close()

    a1 = publish_anchor(db_path=obs_db, batch_max_size=1000)
    a2 = publish_anchor(db_path=obs_db, batch_max_size=1000)
    a3 = publish_anchor(db_path=obs_db, batch_max_size=1000)
    assert a1["batch_end_seq"] + 1 == a2["batch_start_seq"]
    assert a2["batch_end_seq"] + 1 == a3["batch_start_seq"]
