"""Observatory SQLite schema — event_log table for the event bus.

Tables
------
1. event_log — append-only log of all observatory events
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Union

_DDL = """
CREATE TABLE IF NOT EXISTS event_log (
    event_id        TEXT PRIMARY KEY,
    event_type      TEXT NOT NULL,
    timestamp       REAL NOT NULL,
    session_id      TEXT,
    agent_did       TEXT,
    payload         JSON,
    sequence_number INTEGER UNIQUE NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_event_log_type ON event_log(event_type);
CREATE INDEX IF NOT EXISTS idx_event_log_session ON event_log(session_id);
CREATE INDEX IF NOT EXISTS idx_event_log_agent ON event_log(agent_did);
CREATE INDEX IF NOT EXISTS idx_event_log_seq ON event_log(sequence_number);

CREATE TABLE IF NOT EXISTS on_chain_anchor (
    anchor_id          TEXT PRIMARY KEY,
    merkle_root_hex    TEXT NOT NULL,
    batch_start_seq    INTEGER NOT NULL,
    batch_end_seq      INTEGER NOT NULL,
    event_count        INTEGER NOT NULL,
    committed_at       TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    mission_id         TEXT
);

CREATE INDEX IF NOT EXISTS idx_anchor_mission ON on_chain_anchor(mission_id);
CREATE INDEX IF NOT EXISTS idx_anchor_committed_at ON on_chain_anchor(committed_at);
"""


def create_observatory_tables(db_path: Union[str, Path]) -> None:
    """Create the observatory event_log table.  Idempotent (IF NOT EXISTS)."""
    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute("PRAGMA foreign_keys = ON")
        conn.executescript(_DDL)
        conn.commit()

        # Idempotent column addition for Bundle-3 on-chain anchoring
        try:
            conn.execute(
                "ALTER TABLE event_log ADD COLUMN anchor_id TEXT REFERENCES on_chain_anchor(anchor_id)"
            )
            conn.commit()
        except sqlite3.OperationalError as exc:
            if "duplicate column name" not in str(exc).lower():
                raise

        # Idempotent column addition for mission-level reconciliation
        try:
            conn.execute("ALTER TABLE event_log ADD COLUMN mission_id TEXT")
            conn.commit()
        except sqlite3.OperationalError as exc:
            if "duplicate column name" not in str(exc).lower():
                raise
    finally:
        conn.close()
