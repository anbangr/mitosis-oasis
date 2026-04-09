"""Adjudication SQLite schema — 3 new tables for the adjudication layer.

Tables (new)
------------
1. coordination_flag    — detected coordination patterns between agents
2. adjudication_decision — guardian/sanction decisions with audit trail
3. treasury             — platform treasury accounting ledger

NOTE: guardian_alert and agent_balance tables already exist from P12/P13
execution schema and are NOT recreated here.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Union

_DDL = """
-- 1. Coordination flags (detected collusion / coordination patterns)
CREATE TABLE IF NOT EXISTS coordination_flag (
    flag_id      TEXT PRIMARY KEY,
    session_id   TEXT NOT NULL,
    agent_did_1  TEXT NOT NULL,
    agent_did_2  TEXT NOT NULL,
    flag_type    TEXT NOT NULL,
    score        REAL NOT NULL,
    created_at   TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (session_id)  REFERENCES legislative_session(session_id),
    FOREIGN KEY (agent_did_1) REFERENCES agent_registry(agent_did),
    FOREIGN KEY (agent_did_2) REFERENCES agent_registry(agent_did)
);

-- 2. Adjudication decisions (guardian + sanction audit trail)
CREATE TABLE IF NOT EXISTS adjudication_decision (
    decision_id    TEXT PRIMARY KEY,
    alert_id       TEXT,
    flag_id        TEXT,
    agent_did      TEXT NOT NULL,
    decision_type  TEXT NOT NULL,
    severity       TEXT NOT NULL,
    reason         TEXT,
    layer1_result  TEXT,
    layer2_advisory TEXT,
    created_at     TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (alert_id)  REFERENCES guardian_alert(alert_id),
    FOREIGN KEY (flag_id)   REFERENCES coordination_flag(flag_id),
    FOREIGN KEY (agent_did) REFERENCES agent_registry(agent_did)
);

-- 3. Treasury accounting ledger
CREATE TABLE IF NOT EXISTS treasury (
    entry_id    INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id     TEXT,
    agent_did   TEXT,
    entry_type  TEXT NOT NULL,
    amount      REAL NOT NULL,
    balance_after REAL NOT NULL,
    created_at  TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
"""


def create_adjudication_tables(db_path: Union[str, Path]) -> None:
    """Create the 3 adjudication tables.  Idempotent (IF NOT EXISTS)."""
    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute("PRAGMA foreign_keys = ON")
        conn.executescript(_DDL)
        conn.commit()
    finally:
        conn.close()
