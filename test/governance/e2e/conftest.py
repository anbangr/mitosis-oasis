"""Shared fixtures and helpers for E2E governance tests.

Provides a ``drive_session_to_deployed`` helper that walks a fresh
governance DB through the entire legislative pipeline using the real
clerk modules and state machine — no mocks except MockLLM for Layer 2.
"""
from __future__ import annotations

import json
import sqlite3
import uuid
from pathlib import Path
from typing import Optional

import pytest

from oasis.governance.clerks.codifier import Codifier
from oasis.governance.clerks.llm_interface import MockLLM
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


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def e2e_db(tmp_path: Path) -> Path:
    """Fresh governance DB initialised with tables, constitution, and clerks."""
    db = tmp_path / "e2e.db"
    create_governance_tables(db)
    seed_constitution(db)
    seed_clerks(db)
    return db


# Five default producer agents used in most E2E tests.
DEFAULT_PRODUCERS = [
    {
        "agent_did": f"did:e2e:producer-{i}",
        "display_name": f"E2E Producer {i}",
        "reputation_score": 0.5,
    }
    for i in range(1, 6)
]


@pytest.fixture()
def producers(e2e_db: Path) -> list[dict]:
    """Register 5 producer agents in the governance DB."""
    conn = sqlite3.connect(str(e2e_db))
    conn.execute("PRAGMA foreign_keys = ON")
    for p in DEFAULT_PRODUCERS:
        conn.execute(
            "INSERT OR IGNORE INTO agent_registry "
            "(agent_did, agent_type, display_name, human_principal, reputation_score) "
            "VALUES (?, 'producer', ?, 'human@example.com', ?)",
            (p["agent_did"], p["display_name"], p["reputation_score"]),
        )
    conn.commit()
    conn.close()
    return list(DEFAULT_PRODUCERS)


# ---------------------------------------------------------------------------
# Default 3-node DAG used across many tests
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


# ---------------------------------------------------------------------------
# Helper: drive a session through the full legislative pipeline
# ---------------------------------------------------------------------------

def _make_unique_dag(dag: dict, prefix: str) -> dict:
    """Return a copy of the DAG with node_ids prefixed to avoid PK collisions."""
    import copy
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


def drive_session_to_deployed(
    db_path: Path,
    producers: list[dict],
    *,
    session_id: str | None = None,
    dag_spec: dict | None = None,
    total_budget: float = 1000.0,
    min_reputation: float = 0.1,
    llm_enabled: bool = False,
    llm: MockLLM | None = None,
    parent_session_id: str | None = None,
    parent_node_id: str | None = None,
    mission_budget_cap: float | None = None,
    unique_dag: bool = True,
) -> dict:
    """Walk a fresh session from SESSION_INIT all the way to DEPLOYED.

    Returns a dict with all intermediate artefacts:
        session_id, proposal_id, spec_id, approved_bids, sm, messages
    """
    db = str(db_path)
    sid = session_id or f"e2e-sess-{uuid.uuid4().hex[:8]}"
    raw_dag = dag_spec or DEFAULT_DAG
    # Prefix node IDs with session ID to avoid UNIQUE constraint collisions
    dag = _make_unique_dag(raw_dag, sid) if unique_dag else raw_dag

    # Clerk instances
    registrar = Registrar(db_path=db, clerk_did="did:oasis:clerk-registrar",
                          llm_enabled=llm_enabled, llm=llm)
    speaker = Speaker(db_path=db, clerk_did="did:oasis:clerk-speaker",
                      llm_enabled=llm_enabled, llm=llm)
    regulator = Regulator(db_path=db, clerk_did="did:oasis:clerk-regulator",
                          llm_enabled=llm_enabled, llm=llm)
    codifier = Codifier(db_path=db, clerk_did="did:oasis:clerk-codifier",
                        llm_enabled=llm_enabled, llm=llm)

    # --- Create session ---
    conn = sqlite3.connect(db)
    conn.execute("PRAGMA foreign_keys = ON")
    budget = mission_budget_cap if mission_budget_cap is not None else total_budget
    conn.execute(
        "INSERT OR IGNORE INTO legislative_session "
        "(session_id, state, epoch, parent_session_id, parent_node_id, "
        " mission_budget_cap) "
        "VALUES (?, 'SESSION_INIT', 0, ?, ?, ?)",
        (sid, parent_session_id, parent_node_id, budget),
    )
    conn.commit()
    conn.close()

    sm = LegislativeStateMachine(sid, db)

    # --- 1. SESSION_INIT → IDENTITY_VERIFICATION ---
    registrar.open_session(sid, min_reputation)
    result = sm.transition(LegislativeState.IDENTITY_VERIFICATION)
    assert result.allowed, f"→ IDENTITY_VERIFICATION failed: {result.reason}"

    # --- 2. Attest all producers ---
    for p in producers:
        att = IdentityAttestation(
            session_id=sid,
            agent_did=p["agent_did"],
            signature="e2e-sig",
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

    # --- 3. IDENTITY_VERIFICATION → PROPOSAL_OPEN ---
    result = sm.transition(LegislativeState.PROPOSAL_OPEN)
    assert result.allowed, f"→ PROPOSAL_OPEN failed: {result.reason}"

    # --- 4. Submit proposal ---
    proposal = DAGProposal(
        session_id=sid,
        proposer_did=producers[0]["agent_did"],
        dag_spec=dag,
        rationale="E2E test mission",
        token_budget_total=total_budget,
        deadline_ms=60000,
    )
    prop_result = speaker.receive_proposal(sid, proposal)
    assert prop_result["passed"], f"Proposal failed: {prop_result['errors']}"
    proposal_id = prop_result["proposal_id"]

    # --- 5. PROPOSAL_OPEN → BIDDING_OPEN ---
    result = sm.transition(LegislativeState.BIDDING_OPEN)
    assert result.allowed, f"→ BIDDING_OPEN failed: {result.reason}"

    # --- 6. Submit bids — distribute across producers for fairness ---
    nodes = dag["nodes"]
    approved_bids = []
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

    # --- 7. BIDDING_OPEN → REGULATORY_REVIEW ---
    result = sm.transition(LegislativeState.REGULATORY_REVIEW)
    assert result.allowed, f"→ REGULATORY_REVIEW failed: {result.reason}"

    # --- 8. Evaluate bids ---
    eval_result = regulator.evaluate_bids(sid)

    # --- 9. REGULATORY_REVIEW → CODIFICATION ---
    result = sm.transition(LegislativeState.CODIFICATION)
    assert result.allowed, f"→ CODIFICATION failed: {result.reason}"

    # --- 10. Compile and validate spec ---
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

    # --- 11. CODIFICATION → AWAITING_APPROVAL ---
    result = sm.transition(LegislativeState.AWAITING_APPROVAL)
    assert result.allowed, f"→ AWAITING_APPROVAL failed: {result.reason}"

    # --- 12. Dual sign-off → DEPLOYED ---
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
