"""Execution SQLite schema — 7 tables for the execution branch.

Tables
------
1. task_assignment     — maps approved bids to execution tasks
2. task_commitment     — agent stake lockup records
3. task_output         — execution results submitted by agents
4. output_validation   — validation pass/fail + quality scores
5. settlement          — post-execution settlement + rewards/penalties
6. agent_balance       — agent token balances and locked stakes
7. guardian_alert      — alerts emitted by the output validator
"""
from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Union

_DDL = """
-- 1. Task assignments (routed from approved bids after DEPLOYED)
CREATE TABLE IF NOT EXISTS task_assignment (
    task_id     TEXT PRIMARY KEY,
    session_id  TEXT NOT NULL,
    node_id     TEXT NOT NULL,
    agent_did   TEXT NOT NULL,
    status      TEXT NOT NULL DEFAULT 'pending',
    created_at  TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (session_id) REFERENCES legislative_session(session_id),
    FOREIGN KEY (agent_did)  REFERENCES agent_registry(agent_did)
);

-- 2. Task commitments (stake lockup)
CREATE TABLE IF NOT EXISTS task_commitment (
    commitment_id  TEXT PRIMARY KEY,
    task_id        TEXT NOT NULL,
    agent_did      TEXT NOT NULL,
    stake_amount   REAL NOT NULL,
    committed_at   TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (task_id)   REFERENCES task_assignment(task_id),
    FOREIGN KEY (agent_did) REFERENCES agent_registry(agent_did)
);

-- 3. Task outputs (submitted by agents after execution)
CREATE TABLE IF NOT EXISTS task_output (
    output_id    TEXT PRIMARY KEY,
    task_id      TEXT NOT NULL,
    agent_did    TEXT NOT NULL,
    output_data  TEXT,
    latency_ms   INTEGER,
    submitted_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (task_id)   REFERENCES task_assignment(task_id),
    FOREIGN KEY (agent_did) REFERENCES agent_registry(agent_did)
);

-- 4. Output validation results
CREATE TABLE IF NOT EXISTS output_validation (
    validation_id    TEXT PRIMARY KEY,
    task_id          TEXT NOT NULL,
    schema_valid     BOOLEAN,
    timeout_valid    BOOLEAN,
    quality_score    REAL,
    guardian_alert_id TEXT,
    validated_at     TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (task_id) REFERENCES task_assignment(task_id)
);

-- 5. Settlement records
CREATE TABLE IF NOT EXISTS settlement (
    settlement_id         TEXT PRIMARY KEY,
    task_id               TEXT NOT NULL,
    agent_did             TEXT NOT NULL,
    base_reward           REAL NOT NULL,
    reputation_multiplier REAL NOT NULL,
    final_reward          REAL NOT NULL,
    protocol_fee          REAL NOT NULL,
    insurance_fee         REAL NOT NULL,
    treasury_subsidy      REAL NOT NULL DEFAULT 0.0,
    settled_at            TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (task_id)   REFERENCES task_assignment(task_id),
    FOREIGN KEY (agent_did) REFERENCES agent_registry(agent_did)
);

-- 6. Agent balances
CREATE TABLE IF NOT EXISTS agent_balance (
    agent_did         TEXT PRIMARY KEY,
    total_balance     REAL NOT NULL DEFAULT 100.0,
    locked_stake      REAL NOT NULL DEFAULT 0.0,
    available_balance REAL NOT NULL DEFAULT 100.0,
    FOREIGN KEY (agent_did) REFERENCES agent_registry(agent_did)
);

-- 7. Guardian alerts (emitted when output validation fails)
CREATE TABLE IF NOT EXISTS guardian_alert (
    alert_id    TEXT PRIMARY KEY,
    task_id     TEXT NOT NULL,
    alert_type  TEXT NOT NULL,
    severity    TEXT NOT NULL,
    details     TEXT,
    created_at  TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (task_id) REFERENCES task_assignment(task_id)
);
"""


def create_execution_tables(db_path: Union[str, Path]) -> None:
    """Create all 6 execution tables.  Idempotent (IF NOT EXISTS)."""
    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute("PRAGMA foreign_keys = ON")
        conn.executescript(_DDL)
        conn.commit()
    finally:
        conn.close()
