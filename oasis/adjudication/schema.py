"""Adjudication SQLite schema for the adjudication layer.

The live HTTP server initialises adjudication in a branch-local SQLite DB, so
it cannot rely on execution tables existing elsewhere. We therefore recreate
the small subset of cross-branch tables adjudication reads directly.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Union

_DDL = """
-- Cross-branch tables adjudication reads directly in the standalone HTTP path.
CREATE TABLE IF NOT EXISTS agent_balance (
    agent_did          TEXT PRIMARY KEY,
    total_balance      REAL NOT NULL DEFAULT 100.0,
    locked_stake       REAL NOT NULL DEFAULT 0.0,
    available_balance  REAL NOT NULL DEFAULT 100.0
);

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
    decision_id TEXT REFERENCES adjudication_decision(decision_id),
    created_at  TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- 4. Insurance pool ledger
CREATE TABLE IF NOT EXISTS insurance_pool (
    entry_id    INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id     TEXT,
    agent_did   TEXT,
    entry_type  TEXT NOT NULL,
    amount      REAL NOT NULL,
    balance_after REAL NOT NULL,
    decision_id TEXT REFERENCES adjudication_decision(decision_id),
    created_at  TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- 5. Adjudicator registry (MONITOR-type agents)
CREATE TABLE IF NOT EXISTS adjudicator_registry (
    adjudicator_did   TEXT PRIMARY KEY,
    eth_address       TEXT NOT NULL UNIQUE,
    stake_amount      REAL NOT NULL DEFAULT 5000.0,
    is_active         BOOLEAN NOT NULL DEFAULT 1,
    is_banned         BOOLEAN NOT NULL DEFAULT 0,
    registered_at     TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- 6. Impeachment motions (spec §2.1-2.2)
CREATE TABLE IF NOT EXISTS impeachment (
    motion_id         TEXT PRIMARY KEY,
    target_did        TEXT NOT NULL,
    evidence_cid      TEXT NOT NULL,
    signatures_json   TEXT NOT NULL,             -- list of {signer, sig_hex}
    signatures_count  INTEGER NOT NULL,
    required_threshold INTEGER NOT NULL,         -- ceil(2q/3) at motion creation
    status            TEXT NOT NULL CHECK(status IN ('pending', 'accepted', 'rejected')),
    slashed_amount    REAL,
    executed_at       TIMESTAMP,
    created_at        TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (target_did) REFERENCES adjudicator_registry(adjudicator_did)
);

-- 7. Watchdog anomalies (spec §2.4)
CREATE TABLE IF NOT EXISTS watchdog_anomaly (
    anomaly_id        INTEGER PRIMARY KEY AUTOINCREMENT,
    adjudicator_did   TEXT NOT NULL,
    anomaly_type      TEXT NOT NULL CHECK(anomaly_type IN (
                          'approval_rate_deviation',
                          'freeze_lift_rate_deviation'
                      )),
    zscore            REAL NOT NULL,
    window_decisions  INTEGER NOT NULL,
    detected_at       TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (adjudicator_did) REFERENCES adjudicator_registry(adjudicator_did)
);
"""


def create_adjudication_tables(db_path: Union[str, Path]) -> None:
    """Create the adjudication tables.  Idempotent (IF NOT EXISTS)."""
    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute("PRAGMA foreign_keys = ON")
        conn.executescript(_DDL)

        # Idempotent ALTER TABLE for decision_id (legacy tables pick up the column).
        for table in ("treasury", "insurance_pool"):
            try:
                conn.execute(
                    f"ALTER TABLE {table} ADD COLUMN decision_id TEXT "
                    f"REFERENCES adjudication_decision(decision_id)"
                )
                conn.commit()
            except sqlite3.OperationalError:
                # Column already exists; second invocation is a no-op.
                pass

        # Idempotent ALTER TABLE for Bundle-2 adjudication decision columns.
        for column_sql in (
            "ALTER TABLE adjudication_decision ADD COLUMN frozen_at TIMESTAMP",
            "ALTER TABLE adjudication_decision ADD COLUMN manual_extension BOOLEAN NOT NULL DEFAULT 0",
            "ALTER TABLE adjudication_decision ADD COLUMN issued_by_did TEXT",
        ):
            try:
                conn.execute(column_sql)
                conn.commit()
            except sqlite3.OperationalError:
                # Column already exists; second invocation is a no-op.
                pass

        conn.commit()
    finally:
        conn.close()
