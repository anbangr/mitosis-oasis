"""Shared fixtures for execution tests.

Provides governance + execution DB setup and a helper that drives a
legislative session all the way to DEPLOYED so that execution routing
can be tested end-to-end.
"""
from __future__ import annotations

import copy
import json
import sqlite3
import uuid
from pathlib import Path
from typing import Generator

import pytest

from oasis.governance.clerks.codifier import Codifier
from oasis.governance.clerks.registrar import Registrar
from oasis.governance.clerks.regulator import Regulator
from oasis.governance.clerks.speaker import Speaker
from oasis.governance.messages import (
    DAGProposal,
    IdentityAttestation,
    LegislativeApproval,
    TaskBid,
    log_message,
)
from oasis.governance.schema import (
    create_governance_tables,
    seed_clerks,
    seed_constitution,
)
from oasis.governance.state_machine import LegislativeState, LegislativeStateMachine
from oasis.execution.schema import create_execution_tables


# ---------------------------------------------------------------------------
# Core DB fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def db_path(tmp_path: Path) -> Path:
    """Fresh temporary SQLite database path."""
    return tmp_path / "test_execution.db"


@pytest.fixture()
def execution_db(db_path: Path) -> Path:
    """Governance + execution tables initialised with seeds."""
    create_governance_tables(db_path)
    seed_constitution(db_path)
    seed_clerks(db_path)
    create_execution_tables(db_path)
    return db_path


@pytest.fixture()
def db_conn(execution_db: Path) -> Generator[sqlite3.Connection, None, None]:
    """Yield a sqlite3 connection with FK enforcement; auto-close."""
    conn = sqlite3.connect(str(execution_db))
    conn.execute("PRAGMA foreign_keys = ON")
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Producer agents
# ---------------------------------------------------------------------------

EXEC_PRODUCERS = [
    {
        "agent_did": f"did:exec:producer-{i}",
        "display_name": f"Exec Producer {i}",
        "reputation_score": 0.5,
    }
    for i in range(1, 6)
]


@pytest.fixture()
def producers(execution_db: Path) -> list[dict]:
    """Register 5 producer agents in the execution DB."""
    conn = sqlite3.connect(str(execution_db))
    conn.execute("PRAGMA foreign_keys = ON")
    for p in EXEC_PRODUCERS:
        conn.execute(
            "INSERT OR IGNORE INTO agent_registry "
            "(agent_did, agent_type, display_name, human_principal, reputation_score) "
            "VALUES (?, 'producer', ?, 'human@example.com', ?)",
            (p["agent_did"], p["display_name"], p["reputation_score"]),
        )
    conn.commit()
    conn.close()
    return list(EXEC_PRODUCERS)


# ---------------------------------------------------------------------------
# Default DAG
# ---------------------------------------------------------------------------

DEFAULT_DAG = {
    "nodes": [
        {
            "node_id": "root",
            "label": "Coordinate",
            "service_id": "coordinator",
            "pop_tier": 1,
            "token_budget": 600.0,
            "timeout_ms": 60000,
        },
        {
            "node_id": "task-a",
            "label": "Data Collection",
            "service_id": "scraper",
            "pop_tier": 1,
            "token_budget": 200.0,
            "timeout_ms": 60000,
        },
        {
            "node_id": "task-b",
            "label": "Analysis",
            "service_id": "analyzer",
            "pop_tier": 1,
            "token_budget": 200.0,
            "timeout_ms": 60000,
        },
    ],
    "edges": [
        {"from_node_id": "root", "to_node_id": "task-a"},
        {"from_node_id": "root", "to_node_id": "task-b"},
    ],
}


def _make_unique_dag(dag: dict, prefix: str) -> dict:
    """Return a copy of the DAG with node_ids prefixed to avoid PK collisions."""
    d = copy.deepcopy(dag)
    id_map = {}
    for node in d["nodes"]:
        old_id = node["node_id"]
        new_id = f"{prefix}-{old_id}"
        id_map[old_id] = new_id
        node["node_id"] = new_id
    for edge in d.get("edges", []):
        edge["from_node_id"] = id_map[edge["from_node_id"]]
        edge["to_node_id"] = id_map[edge["to_node_id"]]
    return d


# ---------------------------------------------------------------------------
# Helper: drive session to DEPLOYED
# ---------------------------------------------------------------------------

def drive_to_deployed(
    db_path: Path,
    producers: list[dict],
    *,
    session_id: str | None = None,
) -> dict:
    """Walk a fresh session from SESSION_INIT all the way to DEPLOYED.

    Returns a dict with session_id, proposal_id, spec_id, approved_bids, sm.
    """
    db = str(db_path)
    sid = session_id or f"exec-sess-{uuid.uuid4().hex[:8]}"
    dag = _make_unique_dag(DEFAULT_DAG, sid)

    # Clerk instances
    registrar = Registrar(db_path=db, clerk_did="did:oasis:clerk-registrar")
    speaker = Speaker(db_path=db, clerk_did="did:oasis:clerk-speaker")
    regulator = Regulator(db_path=db, clerk_did="did:oasis:clerk-regulator")
    codifier = Codifier(db_path=db, clerk_did="did:oasis:clerk-codifier")

    # Create session
    conn = sqlite3.connect(db)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute(
        "INSERT OR IGNORE INTO legislative_session "
        "(session_id, state, epoch, mission_budget_cap) "
        "VALUES (?, 'SESSION_INIT', 0, 1000.0)",
        (sid,),
    )
    conn.commit()
    conn.close()

    sm = LegislativeStateMachine(sid, db)

    # 1. SESSION_INIT → IDENTITY_VERIFICATION
    registrar.open_session(sid, 0.1)
    result = sm.transition(LegislativeState.IDENTITY_VERIFICATION)
    assert result.allowed, f"→ IDENTITY_VERIFICATION failed: {result.reason}"

    # 2. Attest all producers
    for p in producers:
        att = IdentityAttestation(
            session_id=sid,
            agent_did=p["agent_did"],
            signature="exec-sig",
            reputation_score=p["reputation_score"],
            agent_type="producer",
        )
        res = registrar.verify_identity(att)
        assert res["passed"], f"Identity failed for {p['agent_did']}: {res['errors']}"

    # Insert IdentityVerificationResponse messages (guard requirement)
    conn = sqlite3.connect(db)
    conn.execute("PRAGMA foreign_keys = ON")
    for p in producers:
        conn.execute(
            "INSERT INTO message_log "
            "(session_id, msg_type, sender_did, payload) "
            "VALUES (?, 'IdentityVerificationResponse', ?, '{}')",
            (sid, p["agent_did"]),
        )
    conn.commit()
    conn.close()

    # 3. IDENTITY_VERIFICATION → PROPOSAL_OPEN
    result = sm.transition(LegislativeState.PROPOSAL_OPEN)
    assert result.allowed, f"→ PROPOSAL_OPEN failed: {result.reason}"

    # 4. Submit proposal
    proposal = DAGProposal(
        session_id=sid,
        proposer_did=producers[0]["agent_did"],
        dag_spec=dag,
        rationale="Execution test mission",
        token_budget_total=1000.0,
        deadline_ms=60000,
    )
    prop_result = speaker.receive_proposal(sid, proposal)
    assert prop_result["passed"], f"Proposal failed: {prop_result['errors']}"
    proposal_id = prop_result["proposal_id"]

    # 5. PROPOSAL_OPEN → BIDDING_OPEN
    result = sm.transition(LegislativeState.BIDDING_OPEN)
    assert result.allowed, f"→ BIDDING_OPEN failed: {result.reason}"

    # 6. Submit bids — distribute across producers
    nodes = dag["nodes"]
    for idx, node in enumerate(nodes):
        bidder = producers[idx % len(producers)]
        bid = TaskBid(
            session_id=sid,
            task_node_id=node["node_id"],
            bidder_did=bidder["agent_did"],
            service_id=node["service_id"],
            proposed_code_hash="abcdef1234567890",
            stake_amount=0.5,
            estimated_latency_ms=5000,
            pop_tier_acceptance=node.get("pop_tier", 1),
        )
        bid_result = regulator.receive_bid(sid, bid)
        assert bid_result["passed"], f"Bid failed for {node['node_id']}: {bid_result['errors']}"

    # 7. BIDDING_OPEN → REGULATORY_REVIEW
    result = sm.transition(LegislativeState.REGULATORY_REVIEW)
    assert result.allowed, f"→ REGULATORY_REVIEW failed: {result.reason}"

    # 8. Evaluate bids
    eval_result = regulator.evaluate_bids(sid)

    # 9. REGULATORY_REVIEW → CODIFICATION
    result = sm.transition(LegislativeState.CODIFICATION)
    assert result.allowed, f"→ CODIFICATION failed: {result.reason}"

    # 10. Compile and validate spec
    conn = sqlite3.connect(db)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.row_factory = sqlite3.Row
    bid_rows = conn.execute(
        "SELECT * FROM bid WHERE session_id = ? AND status = 'approved'",
        (sid,),
    ).fetchall()
    approved_bids_list = [dict(b) for b in bid_rows]
    conn.close()

    spec = codifier.compile_spec(sid, proposal, approved_bids_list)
    val_result = codifier.run_constitutional_validation(spec)
    assert val_result.passed, f"Constitutional validation failed: {val_result.errors}"

    # 11. CODIFICATION → AWAITING_APPROVAL
    result = sm.transition(LegislativeState.AWAITING_APPROVAL)
    assert result.allowed, f"→ AWAITING_APPROVAL failed: {result.reason}"

    # 12. Dual sign-off → DEPLOYED
    speaker_sig = speaker.issue_approval(sid, spec.validation_proof)
    reg_sig = regulator.co_sign_approval(sid, spec.validation_proof)

    msg7 = LegislativeApproval(
        session_id=sid,
        spec_id=spec.validation_proof,
        speaker_signature=speaker_sig["speaker_signature"],
        regulator_signature=reg_sig,
    )
    log_message(db, sid, msg7, sender_did="system")

    result = sm.transition(
        LegislativeState.DEPLOYED,
        signatures={"proposer": speaker_sig["speaker_signature"], "regulator": reg_sig},
    )
    assert result.allowed, f"→ DEPLOYED failed: {result.reason}"

    return {
        "session_id": sid,
        "proposal_id": proposal_id,
        "spec_id": spec.validation_proof,
        "approved_bids": eval_result.get("approved_bids", []),
        "sm": sm,
        "spec": spec,
        "eval_result": eval_result,
    }


@pytest.fixture()
def deployed_session(execution_db: Path, producers: list[dict]) -> dict:
    """A fully DEPLOYED session with approved bids, ready for routing."""
    return drive_to_deployed(execution_db, producers)
