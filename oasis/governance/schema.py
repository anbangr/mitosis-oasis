"""Governance SQLite schema — 15 tables for the legislative protocol.

Tables
------
1.  constitution             — constitutional parameters (key-value)
2.  agent_registry           — all agents (producers + clerks)
3.  clerk_registry           — clerk-specific metadata
4.  legislative_session      — legislative session state machine
5.  proposal                 — proposals submitted during a session
6.  dag_node                 — DAG task nodes within a proposal
7.  dag_edge                 — DAG edges (dependencies) between nodes
8.  bid                      — bids on task nodes
9.  regulatory_decision      — Regulator's per-session decision record
10. straw_poll               — pre-deliberation straw poll preferences
11. deliberation_round       — deliberation messages
12. vote                     — formal votes (ordinal preference rankings)
13. contract_spec            — codified contract specifications
14. reputation_ledger        — reputation score changelog
15. message_log              — append-only protocol message log
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Union

# ---------------------------------------------------------------------------
# DDL statements
# ---------------------------------------------------------------------------

_DDL = """
-- 1. Constitutional parameters (key-value store)
CREATE TABLE IF NOT EXISTS constitution (
    param_name   TEXT PRIMARY KEY,
    param_value  REAL NOT NULL,
    param_type   TEXT NOT NULL DEFAULT 'float',
    description  TEXT,
    updated_at   TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- 2. Agent registry (producers + clerks)
CREATE TABLE IF NOT EXISTS agent_registry (
    agent_did         TEXT PRIMARY KEY,
    agent_type        TEXT NOT NULL CHECK(agent_type IN ('producer', 'clerk')),
    capability_tier   TEXT NOT NULL DEFAULT 't1' CHECK(capability_tier IN ('t1', 't3', 't5')),
    display_name      TEXT NOT NULL,
    human_principal   TEXT,
    reputation_score  REAL NOT NULL DEFAULT 0.5,
    registered_at     TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    active            BOOLEAN NOT NULL DEFAULT 1
);

-- 3. Clerk registry (extends agent_registry for clerks)
CREATE TABLE IF NOT EXISTS clerk_registry (
    agent_did          TEXT PRIMARY KEY,
    clerk_role         TEXT NOT NULL CHECK(clerk_role IN ('registrar', 'speaker', 'regulator', 'codifier')),
    authority_envelope TEXT NOT NULL,
    FOREIGN KEY (agent_did) REFERENCES agent_registry(agent_did)
);

-- 4. Legislative sessions
CREATE TABLE IF NOT EXISTS legislative_session (
    session_id         TEXT PRIMARY KEY,
    state              TEXT NOT NULL DEFAULT 'SESSION_INIT',
    epoch              INTEGER NOT NULL DEFAULT 0,
    parent_session_id  TEXT,
    parent_node_id     TEXT,
    mission_budget_cap REAL,
    created_at         TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at         TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    failed_reason      TEXT,
    FOREIGN KEY (parent_session_id) REFERENCES legislative_session(session_id)
);

-- 5. Proposals
CREATE TABLE IF NOT EXISTS proposal (
    proposal_id        TEXT PRIMARY KEY,
    session_id         TEXT NOT NULL,
    proposer_did       TEXT NOT NULL,
    dag_spec           TEXT NOT NULL,
    rationale          TEXT,
    token_budget_total REAL NOT NULL,
    deadline_ms        INTEGER NOT NULL,
    status             TEXT NOT NULL DEFAULT 'submitted',
    created_at         TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (session_id)   REFERENCES legislative_session(session_id),
    FOREIGN KEY (proposer_did) REFERENCES agent_registry(agent_did)
);

-- 6. DAG nodes (task nodes within a proposal)
CREATE TABLE IF NOT EXISTS dag_node (
    node_id             TEXT PRIMARY KEY,
    proposal_id         TEXT NOT NULL,
    label               TEXT NOT NULL,
    service_id          TEXT,
    input_schema        TEXT,
    output_schema       TEXT,
    pop_tier            INTEGER NOT NULL CHECK(pop_tier BETWEEN 1 AND 3),
    redundancy_factor   INTEGER NOT NULL DEFAULT 1,
    consensus_threshold INTEGER NOT NULL DEFAULT 1,
    token_budget        REAL NOT NULL,
    timeout_ms          INTEGER NOT NULL,
    risk_tier           TEXT,
    FOREIGN KEY (proposal_id) REFERENCES proposal(proposal_id)
);

-- 7. DAG edges (dependencies between nodes)
CREATE TABLE IF NOT EXISTS dag_edge (
    edge_id         INTEGER PRIMARY KEY AUTOINCREMENT,
    proposal_id     TEXT NOT NULL,
    from_node_id    TEXT NOT NULL,
    to_node_id      TEXT NOT NULL,
    data_flow_schema TEXT,
    FOREIGN KEY (proposal_id)  REFERENCES proposal(proposal_id),
    FOREIGN KEY (from_node_id) REFERENCES dag_node(node_id),
    FOREIGN KEY (to_node_id)   REFERENCES dag_node(node_id)
);

-- 8. Bids on task nodes
CREATE TABLE IF NOT EXISTS bid (
    bid_id               TEXT PRIMARY KEY,
    session_id           TEXT NOT NULL,
    task_node_id         TEXT NOT NULL,
    bidder_did           TEXT NOT NULL,
    service_id           TEXT,
    proposed_code_hash   TEXT,
    stake_amount         REAL NOT NULL DEFAULT 0.0,
    estimated_latency_ms INTEGER,
    pop_tier_acceptance  INTEGER,
    status               TEXT NOT NULL DEFAULT 'pending',
    created_at           TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (session_id)   REFERENCES legislative_session(session_id),
    FOREIGN KEY (task_node_id) REFERENCES dag_node(node_id),
    FOREIGN KEY (bidder_did)   REFERENCES agent_registry(agent_did)
);

-- 9. Regulatory decisions
CREATE TABLE IF NOT EXISTS regulatory_decision (
    decision_id          TEXT PRIMARY KEY,
    session_id           TEXT NOT NULL,
    approved_bids        TEXT,
    rejected_bids        TEXT,
    fairness_score       REAL,
    compliance_flags     TEXT,
    regulatory_signature TEXT,
    created_at           TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (session_id) REFERENCES legislative_session(session_id)
);

-- 10. Straw polls (pre-deliberation)
CREATE TABLE IF NOT EXISTS straw_poll (
    poll_id            INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id         TEXT NOT NULL,
    agent_did          TEXT NOT NULL,
    proposal_id        TEXT NOT NULL,
    preference_ranking TEXT NOT NULL,
    created_at         TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (session_id)  REFERENCES legislative_session(session_id),
    FOREIGN KEY (agent_did)   REFERENCES agent_registry(agent_did),
    FOREIGN KEY (proposal_id) REFERENCES proposal(proposal_id)
);

-- 11. Deliberation rounds
CREATE TABLE IF NOT EXISTS deliberation_round (
    round_id     INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id   TEXT NOT NULL,
    round_number INTEGER NOT NULL CHECK(round_number BETWEEN 1 AND 3),
    agent_did    TEXT NOT NULL,
    message      TEXT NOT NULL,
    created_at   TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (session_id) REFERENCES legislative_session(session_id),
    FOREIGN KEY (agent_did)  REFERENCES agent_registry(agent_did)
);

-- 12. Formal votes (ordinal preference rankings)
CREATE TABLE IF NOT EXISTS vote (
    vote_id            INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id         TEXT NOT NULL,
    agent_did          TEXT NOT NULL,
    preference_ranking TEXT NOT NULL,
    created_at         TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (session_id) REFERENCES legislative_session(session_id),
    FOREIGN KEY (agent_did)  REFERENCES agent_registry(agent_did)
);

-- 13. Contract specifications (codified by Codifier)
CREATE TABLE IF NOT EXISTS contract_spec (
    spec_id                    TEXT PRIMARY KEY,
    session_id                 TEXT NOT NULL,
    collaboration_contract_spec TEXT,
    guardian_module_spec        TEXT,
    verification_module_spec   TEXT,
    gate_module_spec           TEXT,
    service_contract_specs     TEXT,
    validation_proof           TEXT,
    status                     TEXT NOT NULL DEFAULT 'draft',
    created_at                 TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (session_id) REFERENCES legislative_session(session_id)
);

-- 14. Reputation ledger (append-only score changes)
CREATE TABLE IF NOT EXISTS reputation_ledger (
    entry_id          INTEGER PRIMARY KEY AUTOINCREMENT,
    agent_did         TEXT NOT NULL,
    old_score         REAL NOT NULL,
    new_score         REAL NOT NULL,
    performance_score REAL,
    lambda            REAL,
    reason            TEXT,
    created_at        TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (agent_did) REFERENCES agent_registry(agent_did)
);

-- 15. Message log (append-only protocol messages)
CREATE TABLE IF NOT EXISTS message_log (
    log_id      INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id  TEXT NOT NULL,
    msg_type    TEXT NOT NULL,
    sender_did  TEXT NOT NULL,
    receiver    TEXT,
    payload     TEXT,
    created_at  TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (session_id) REFERENCES legislative_session(session_id)
);
"""

# ---------------------------------------------------------------------------
# Default constitutional parameters (from the paper)
# ---------------------------------------------------------------------------

_DEFAULT_CONSTITUTION = [
    ("budget_cap_max",          1_000_000.0, "float",   "Maximum mission budget cap (tokens)"),
    ("budget_cap_min",          1.0,         "float",   "Minimum mission budget cap (tokens)"),
    ("quorum_threshold",        0.51,        "float",   "Fraction of eligible voters needed for quorum"),
    ("max_deliberation_rounds", 3.0,         "integer", "Maximum deliberation rounds per session"),
    ("reputation_floor",        0.1,         "float",   "Minimum reputation score to participate"),
    ("fairness_hhi_threshold",  0.25,        "float",   "HHI threshold above which bid concentration is flagged"),
    ("proposal_deadline_max_ms", 86_400_000.0, "integer", "Maximum proposal deadline (ms) — 24 hours"),
    ("voting_method",           1.0,         "integer", "Voting method (1 = Copeland with Minimax tie-break)"),
    ("max_dag_depth",           10.0,        "integer", "Maximum DAG depth (recursive decomposition limit)"),
    ("max_dag_nodes",           50.0,        "integer", "Maximum nodes per proposal DAG"),
]

# ---------------------------------------------------------------------------
# Default clerk agents
# ---------------------------------------------------------------------------

_CLERK_ROLES = ["registrar", "speaker", "regulator", "codifier"]

_DEFAULT_CLERKS = [
    {
        "agent_did": f"did:oasis:clerk-{role}",
        "agent_type": "clerk",
        "display_name": f"Clerk ({role.title()})",
        "human_principal": "platform@mitosis.dev",
        "clerk_role": role,
        "authority_envelope": json.dumps({
            "role": role,
            "permissions": [f"{role}:*"],
            "issued_at": "2026-01-01T00:00:00Z",
        }),
    }
    for role in _CLERK_ROLES
]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def create_governance_tables(db_path: Union[str, Path]) -> None:
    """Create all 15 governance tables.  Idempotent (IF NOT EXISTS)."""
    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute("PRAGMA foreign_keys = ON")
        conn.executescript(_DDL)
        conn.commit()
    finally:
        conn.close()


def seed_constitution(db_path: Union[str, Path]) -> None:
    """Insert default constitutional parameters from the paper.

    Existing rows with matching ``param_name`` are left unchanged
    (INSERT OR IGNORE).
    """
    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute("PRAGMA foreign_keys = ON")
        conn.executemany(
            "INSERT OR IGNORE INTO constitution "
            "(param_name, param_value, param_type, description) "
            "VALUES (?, ?, ?, ?)",
            _DEFAULT_CONSTITUTION,
        )
        conn.commit()
    finally:
        conn.close()


def seed_clerks(db_path: Union[str, Path]) -> None:
    """Register the 4 clerk agents with authority envelopes.

    Inserts into both ``agent_registry`` and ``clerk_registry``.
    Idempotent (INSERT OR IGNORE).
    """
    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute("PRAGMA foreign_keys = ON")
        for clerk in _DEFAULT_CLERKS:
            conn.execute(
                "INSERT OR IGNORE INTO agent_registry "
                "(agent_did, agent_type, display_name, human_principal) "
                "VALUES (?, ?, ?, ?)",
                (
                    clerk["agent_did"],
                    clerk["agent_type"],
                    clerk["display_name"],
                    clerk["human_principal"],
                ),
            )
            conn.execute(
                "INSERT OR IGNORE INTO clerk_registry "
                "(agent_did, clerk_role, authority_envelope) "
                "VALUES (?, ?, ?)",
                (
                    clerk["agent_did"],
                    clerk["clerk_role"],
                    clerk["authority_envelope"],
                ),
            )
        conn.commit()
    finally:
        conn.close()
