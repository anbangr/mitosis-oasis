"""Governance API endpoints — full legislative pipeline over HTTP.

Provides FastAPI routes for all phases of the AgentCity legislative protocol:
sessions, identity, proposals, deliberation, voting, bidding, regulatory review,
codification, approval, deployment, and constitution queries.
"""
from __future__ import annotations

import json
import sqlite3
import uuid
from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from oasis.governance.clerks.codifier import Codifier
from oasis.governance.clerks.registrar import Registrar
from oasis.governance.clerks.regulator import Regulator
from oasis.governance.clerks.speaker import Speaker
from oasis.governance.messages import (
    CodedContractSpec,
    DAGProposal,
    IdentityAttestation,
    LegislativeApproval,
    TaskBid,
    get_session_messages,
    log_message,
)
from oasis.governance.schema import (
    create_governance_tables,
    seed_clerks,
    seed_constitution,
)
from oasis.governance.state_machine import LegislativeState, LegislativeStateMachine

# ---------------------------------------------------------------------------
# Module-level state: path to governance SQLite database
# ---------------------------------------------------------------------------

_db_path: str | None = None


def init_governance_db(db_path: str) -> None:
    """Initialise the governance database (tables + seeds). Idempotent."""
    global _db_path
    _db_path = db_path
    create_governance_tables(db_path)
    seed_constitution(db_path)
    seed_clerks(db_path)


def _get_db() -> str:
    if _db_path is None:
        raise HTTPException(503, "Governance database not initialised")
    return _db_path


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(_get_db())
    conn.execute("PRAGMA foreign_keys = ON")
    conn.row_factory = sqlite3.Row
    return conn


# ---------------------------------------------------------------------------
# Clerk helpers
# ---------------------------------------------------------------------------

def _registrar() -> Registrar:
    return Registrar(db_path=_get_db(), clerk_did="did:oasis:clerk-registrar")


def _speaker() -> Speaker:
    return Speaker(db_path=_get_db(), clerk_did="did:oasis:clerk-speaker")


def _regulator() -> Regulator:
    return Regulator(db_path=_get_db(), clerk_did="did:oasis:clerk-regulator")


def _codifier() -> Codifier:
    return Codifier(db_path=_get_db(), clerk_did="did:oasis:clerk-codifier")


# ---------------------------------------------------------------------------
# State gate helper
# ---------------------------------------------------------------------------

def _require_state(session_id: str, *allowed: LegislativeState) -> LegislativeState:
    """Return the current session state if it is one of *allowed*, else 409."""
    conn = _connect()
    try:
        row = conn.execute(
            "SELECT state FROM legislative_session WHERE session_id = ?",
            (session_id,),
        ).fetchone()
    finally:
        conn.close()
    if row is None:
        raise HTTPException(404, f"Session not found: {session_id}")
    current = LegislativeState(row["state"])
    if current not in allowed:
        raise HTTPException(
            409,
            f"Session is in state {current.value}; "
            f"expected one of {[s.value for s in allowed]}",
        )
    return current


# ---------------------------------------------------------------------------
# Pydantic request / response bodies
# ---------------------------------------------------------------------------

class CreateSessionBody(BaseModel):
    mission_budget_cap: float = Field(1000.0, gt=0)
    min_reputation: float = Field(0.1, ge=0.0, le=1.0)


class IdentityRequestBody(BaseModel):
    min_reputation: float = Field(0.1, ge=0.0, le=1.0)


class AttestationBody(BaseModel):
    agent_did: str = Field(..., min_length=1)
    signature: str = Field(..., min_length=1)
    reputation_score: float = Field(..., ge=0.0, le=1.0)
    agent_type: str = Field("producer", pattern=r"^(producer|clerk)$")


class ProposalBody(BaseModel):
    proposer_did: str = Field(..., min_length=1)
    dag_spec: dict = Field(...)
    rationale: str = Field("", min_length=0)
    token_budget_total: float = Field(..., gt=0)
    deadline_ms: int = Field(..., gt=0)


class StrawPollBody(BaseModel):
    ballots: dict[str, list[str]] = Field(...)


class DiscussBody(BaseModel):
    agent_did: str = Field(..., min_length=1)
    round_number: int = Field(..., ge=1)
    message: str = Field(..., min_length=1)


class VoteBody(BaseModel):
    ballots: dict[str, list[str]] = Field(...)


class BidBody(BaseModel):
    task_node_id: str = Field(..., min_length=1)
    bidder_did: str = Field(..., min_length=1)
    service_id: str = Field(..., min_length=1)
    proposed_code_hash: str = Field(..., min_length=1)
    stake_amount: float = Field(..., ge=0)
    estimated_latency_ms: int = Field(..., gt=0)
    pop_tier_acceptance: int = Field(..., ge=1, le=3)


class RegulatoryDecisionBody(BaseModel):
    submitter_did: str = Field(..., min_length=1)


class SpecBody(BaseModel):
    proposal_id: str = Field(..., min_length=1)


class ApprovalBody(BaseModel):
    spec_id: str = Field(..., min_length=1)
    proposer_signature: str = Field("", min_length=0)
    regulator_signature: str = Field("", min_length=0)


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------

router = APIRouter(prefix="/api/governance", tags=["Governance"])


# ========================= P8.1 Session management =========================

@router.post("/sessions", status_code=201)
async def create_session(body: CreateSessionBody):
    """Create a new legislative session."""
    db = _get_db()
    session_id = f"sess-{uuid.uuid4().hex[:12]}"
    conn = _connect()
    try:
        conn.execute(
            "INSERT INTO legislative_session "
            "(session_id, state, epoch, mission_budget_cap) "
            "VALUES (?, ?, 0, ?)",
            (session_id, LegislativeState.SESSION_INIT.value, body.mission_budget_cap),
        )
        conn.commit()
    finally:
        conn.close()
    return {"session_id": session_id, "state": LegislativeState.SESSION_INIT.value}


@router.get("/sessions/{session_id}")
async def get_session(session_id: str):
    """Get session state."""
    conn = _connect()
    try:
        row = conn.execute(
            "SELECT * FROM legislative_session WHERE session_id = ?",
            (session_id,),
        ).fetchone()
    finally:
        conn.close()
    if row is None:
        raise HTTPException(404, f"Session not found: {session_id}")
    return {
        "session_id": row["session_id"],
        "state": row["state"],
        "epoch": row["epoch"],
        "mission_budget_cap": row["mission_budget_cap"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "failed_reason": row["failed_reason"],
    }


@router.get("/sessions/{session_id}/messages")
async def get_messages(session_id: str):
    """Get protocol messages for a session."""
    conn = _connect()
    try:
        row = conn.execute(
            "SELECT session_id FROM legislative_session WHERE session_id = ?",
            (session_id,),
        ).fetchone()
    finally:
        conn.close()
    if row is None:
        raise HTTPException(404, f"Session not found: {session_id}")
    messages = get_session_messages(_get_db(), session_id)
    return {"session_id": session_id, "messages": messages}


# ========================= P8.2 Identity ===================================

@router.post("/sessions/{session_id}/identity/request", status_code=200)
async def request_identity_verification(session_id: str, body: IdentityRequestBody):
    """Registrar opens identity-verification phase (MSG1)."""
    _require_state(session_id, LegislativeState.SESSION_INIT)
    registrar = _registrar()

    # Register sample producers if none exist
    conn = _connect()
    try:
        producers = conn.execute(
            "SELECT COUNT(*) FROM agent_registry WHERE agent_type = 'producer' AND active = 1"
        ).fetchone()[0]
    finally:
        conn.close()
    if producers == 0:
        raise HTTPException(400, "No producer agents registered")

    msg1 = registrar.open_session(session_id, body.min_reputation)

    # Transition to IDENTITY_VERIFICATION
    sm = LegislativeStateMachine(session_id, _get_db())
    result = sm.transition(LegislativeState.IDENTITY_VERIFICATION)
    if not result.allowed:
        raise HTTPException(409, result.reason)

    return {
        "session_id": session_id,
        "state": LegislativeState.IDENTITY_VERIFICATION.value,
        "min_reputation": body.min_reputation,
    }


@router.post("/sessions/{session_id}/identity/attest", status_code=200)
async def submit_attestation(session_id: str, body: AttestationBody):
    """Agent submits identity attestation (MSG2)."""
    _require_state(session_id, LegislativeState.IDENTITY_VERIFICATION)
    registrar = _registrar()

    attestation = IdentityAttestation(
        session_id=session_id,
        agent_did=body.agent_did,
        signature=body.signature,
        reputation_score=body.reputation_score,
        agent_type=body.agent_type,
    )
    result = registrar.verify_identity(attestation)
    if not result["passed"]:
        raise HTTPException(400, {"errors": result["errors"]})
    return result


# ========================= P8.3 Proposal ===================================

@router.post("/sessions/{session_id}/proposals", status_code=201)
async def submit_proposal(session_id: str, body: ProposalBody):
    """Submit a DAG proposal (MSG3)."""
    _require_state(session_id, LegislativeState.PROPOSAL_OPEN)
    speaker = _speaker()

    proposal = DAGProposal(
        session_id=session_id,
        proposer_did=body.proposer_did,
        dag_spec=body.dag_spec,
        rationale=body.rationale or "No rationale provided",
        token_budget_total=body.token_budget_total,
        deadline_ms=body.deadline_ms,
    )
    result = speaker.receive_proposal(session_id, proposal)
    if not result["passed"]:
        raise HTTPException(400, {"errors": result["errors"]})
    return result


@router.get("/sessions/{session_id}/proposals/{proposal_id}")
async def get_proposal(session_id: str, proposal_id: str):
    """Get proposal details."""
    conn = _connect()
    try:
        row = conn.execute(
            "SELECT * FROM proposal WHERE proposal_id = ? AND session_id = ?",
            (proposal_id, session_id),
        ).fetchone()
    finally:
        conn.close()
    if row is None:
        raise HTTPException(404, f"Proposal not found: {proposal_id}")
    return {
        "proposal_id": row["proposal_id"],
        "session_id": row["session_id"],
        "proposer_did": row["proposer_did"],
        "dag_spec": json.loads(row["dag_spec"]) if row["dag_spec"] else {},
        "rationale": row["rationale"],
        "token_budget_total": row["token_budget_total"],
        "deadline_ms": row["deadline_ms"],
        "status": row["status"],
        "created_at": row["created_at"],
    }


# ========================= P8.4 Deliberation ================================

@router.post("/sessions/{session_id}/deliberation/straw-poll", status_code=200)
async def submit_straw_poll(session_id: str, body: StrawPollBody):
    """Submit straw poll ballots."""
    _require_state(
        session_id,
        LegislativeState.PROPOSAL_OPEN,
        LegislativeState.BIDDING_OPEN,
    )
    speaker = _speaker()
    result = speaker.collect_straw_poll(session_id, body.ballots)
    return result


@router.post("/sessions/{session_id}/deliberation/discuss", status_code=200)
async def submit_discussion(session_id: str, body: DiscussBody):
    """Submit a deliberation message."""
    _require_state(
        session_id,
        LegislativeState.PROPOSAL_OPEN,
        LegislativeState.BIDDING_OPEN,
    )
    speaker = _speaker()

    # Check round limit
    conn = _connect()
    try:
        max_rounds_row = conn.execute(
            "SELECT param_value FROM constitution "
            "WHERE param_name = 'max_deliberation_rounds'"
        ).fetchone()
        max_rounds = int(max_rounds_row[0]) if max_rounds_row else 3

        if body.round_number > max_rounds:
            raise HTTPException(400, f"Round {body.round_number} exceeds max ({max_rounds})")

        # Store the deliberation message
        conn.execute(
            "INSERT INTO deliberation_round "
            "(session_id, round_number, agent_did, message) "
            "VALUES (?, ?, ?, ?)",
            (session_id, body.round_number, body.agent_did, body.message),
        )
        conn.commit()
    finally:
        conn.close()

    round_info = speaker.open_deliberation_round(session_id, body.round_number)
    return {
        "round_number": body.round_number,
        "agent_did": body.agent_did,
        "speaking_order": round_info.get("speaking_order", []),
    }


@router.get("/sessions/{session_id}/deliberation/summary")
async def get_deliberation_summary(session_id: str):
    """Get deliberation summary for all rounds."""
    conn = _connect()
    try:
        row = conn.execute(
            "SELECT session_id FROM legislative_session WHERE session_id = ?",
            (session_id,),
        ).fetchone()
        if row is None:
            raise HTTPException(404, f"Session not found: {session_id}")

        rounds_data = []
        for round_num in range(1, 4):
            messages = conn.execute(
                "SELECT agent_did, message, created_at "
                "FROM deliberation_round "
                "WHERE session_id = ? AND round_number = ? "
                "ORDER BY round_id",
                (session_id, round_num),
            ).fetchall()
            if messages:
                rounds_data.append({
                    "round_number": round_num,
                    "messages": [
                        {
                            "agent_did": m["agent_did"],
                            "message": m["message"],
                            "created_at": m["created_at"],
                        }
                        for m in messages
                    ],
                })
    finally:
        conn.close()

    return {"session_id": session_id, "rounds": rounds_data}


# ========================= P8.5 Voting =====================================

@router.post("/sessions/{session_id}/vote", status_code=200)
async def submit_vote(session_id: str, body: VoteBody):
    """Submit formal vote rankings."""
    _require_state(
        session_id,
        LegislativeState.PROPOSAL_OPEN,
        LegislativeState.BIDDING_OPEN,
    )
    speaker = _speaker()

    # Validate that all ballots rank the same candidates
    if not body.ballots:
        raise HTTPException(400, "No ballots provided")
    rankings = list(body.ballots.values())
    expected = set(rankings[0])
    for agent_did, ranking in body.ballots.items():
        if set(ranking) != expected:
            raise HTTPException(
                400,
                f"Incomplete ranking from {agent_did}: "
                f"expected {sorted(expected)}, got {sorted(ranking)}",
            )

    result = speaker.tabulate_votes(session_id, body.ballots)
    return result


@router.get("/sessions/{session_id}/vote/results")
async def get_vote_results(session_id: str):
    """Get voting results for a session."""
    conn = _connect()
    try:
        row = conn.execute(
            "SELECT session_id FROM legislative_session WHERE session_id = ?",
            (session_id,),
        ).fetchone()
        if row is None:
            raise HTTPException(404, f"Session not found: {session_id}")

        votes = conn.execute(
            "SELECT agent_did, preference_ranking, created_at "
            "FROM vote WHERE session_id = ? ORDER BY vote_id",
            (session_id,),
        ).fetchall()
    finally:
        conn.close()

    return {
        "session_id": session_id,
        "votes": [
            {
                "agent_did": v["agent_did"],
                "preference_ranking": json.loads(v["preference_ranking"]),
                "created_at": v["created_at"],
            }
            for v in votes
        ],
        "total_votes": len(votes),
    }


# ========================= P8.6 Bidding ====================================

@router.post("/sessions/{session_id}/bids", status_code=201)
async def submit_bid(session_id: str, body: BidBody):
    """Submit a bid on a task node (MSG4)."""
    _require_state(session_id, LegislativeState.BIDDING_OPEN)
    regulator = _regulator()

    bid = TaskBid(
        session_id=session_id,
        task_node_id=body.task_node_id,
        bidder_did=body.bidder_did,
        service_id=body.service_id,
        proposed_code_hash=body.proposed_code_hash,
        stake_amount=body.stake_amount,
        estimated_latency_ms=body.estimated_latency_ms,
        pop_tier_acceptance=body.pop_tier_acceptance,
    )
    result = regulator.receive_bid(session_id, bid)
    if not result["passed"]:
        raise HTTPException(400, {"errors": result["errors"]})
    return result


@router.get("/sessions/{session_id}/bids")
async def list_bids(session_id: str):
    """List all bids for a session."""
    conn = _connect()
    try:
        row = conn.execute(
            "SELECT session_id FROM legislative_session WHERE session_id = ?",
            (session_id,),
        ).fetchone()
        if row is None:
            raise HTTPException(404, f"Session not found: {session_id}")

        bids = conn.execute(
            "SELECT * FROM bid WHERE session_id = ? ORDER BY created_at",
            (session_id,),
        ).fetchall()
    finally:
        conn.close()

    return {
        "session_id": session_id,
        "bids": [
            {
                "bid_id": b["bid_id"],
                "task_node_id": b["task_node_id"],
                "bidder_did": b["bidder_did"],
                "service_id": b["service_id"],
                "stake_amount": b["stake_amount"],
                "estimated_latency_ms": b["estimated_latency_ms"],
                "pop_tier_acceptance": b["pop_tier_acceptance"],
                "status": b["status"],
                "created_at": b["created_at"],
            }
            for b in bids
        ],
    }


# ========================= P8.7 Regulatory =================================

@router.post("/sessions/{session_id}/regulatory/decision", status_code=200)
async def submit_regulatory_decision(session_id: str, body: RegulatoryDecisionBody):
    """Regulator evaluates bids and produces MSG5."""
    _require_state(session_id, LegislativeState.REGULATORY_REVIEW)

    # Only the regulator clerk can submit
    if body.submitter_did != "did:oasis:clerk-regulator":
        raise HTTPException(403, "Only the regulator clerk can submit regulatory decisions")

    regulator = _regulator()
    result = regulator.evaluate_bids(session_id)
    return result


@router.get("/sessions/{session_id}/regulatory/evidence")
async def get_evidence(session_id: str):
    """Get evidence briefing for deliberation."""
    conn = _connect()
    try:
        row = conn.execute(
            "SELECT session_id FROM legislative_session WHERE session_id = ?",
            (session_id,),
        ).fetchone()
    finally:
        conn.close()
    if row is None:
        raise HTTPException(404, f"Session not found: {session_id}")
    regulator = _regulator()
    return regulator.publish_evidence(session_id)


# ========================= P8.8 Codification ===============================

@router.post("/sessions/{session_id}/codification/spec", status_code=201)
async def submit_spec(session_id: str, body: SpecBody):
    """Codifier compiles deployment spec (MSG6)."""
    _require_state(session_id, LegislativeState.CODIFICATION)
    codifier = _codifier()

    # Retrieve proposal
    conn = _connect()
    try:
        prop_row = conn.execute(
            "SELECT * FROM proposal WHERE proposal_id = ? AND session_id = ?",
            (body.proposal_id, session_id),
        ).fetchone()
        if prop_row is None:
            raise HTTPException(404, f"Proposal not found: {body.proposal_id}")

        # Get approved bids
        bids = conn.execute(
            "SELECT * FROM bid WHERE session_id = ? AND status = 'approved'",
            (session_id,),
        ).fetchall()
        approved_bids = [dict(b) for b in bids]
    finally:
        conn.close()

    proposal = DAGProposal(
        session_id=session_id,
        proposer_did=prop_row["proposer_did"],
        dag_spec=json.loads(prop_row["dag_spec"]) if prop_row["dag_spec"] else {},
        rationale=prop_row["rationale"] or "No rationale",
        token_budget_total=prop_row["token_budget_total"],
        deadline_ms=prop_row["deadline_ms"],
    )

    spec = codifier.compile_spec(session_id, proposal, approved_bids)

    # Run constitutional validation
    val_result = codifier.run_constitutional_validation(spec)
    if not val_result.passed:
        errors = [
            {"check": e.check, "field": e.field, "message": e.message}
            for e in val_result.errors
        ]
        raise HTTPException(400, {"errors": errors, "validation": "failed"})

    return {
        "spec_id": spec.validation_proof,
        "session_id": session_id,
        "status": "validated",
    }


@router.get("/sessions/{session_id}/codification/spec")
async def get_spec(session_id: str):
    """Get the contract spec for a session."""
    conn = _connect()
    try:
        row = conn.execute(
            "SELECT session_id FROM legislative_session WHERE session_id = ?",
            (session_id,),
        ).fetchone()
        if row is None:
            raise HTTPException(404, f"Session not found: {session_id}")

        specs = conn.execute(
            "SELECT * FROM contract_spec WHERE session_id = ? ORDER BY created_at DESC",
            (session_id,),
        ).fetchall()
    finally:
        conn.close()

    if not specs:
        return {"session_id": session_id, "specs": []}

    return {
        "session_id": session_id,
        "specs": [
            {
                "spec_id": s["spec_id"],
                "status": s["status"],
                "validation_proof": s["validation_proof"],
                "created_at": s["created_at"],
            }
            for s in specs
        ],
    }


# ========================= P8.9 Approval & deployment ======================

@router.post("/sessions/{session_id}/approval", status_code=200)
async def submit_approval(session_id: str, body: ApprovalBody):
    """Dual sign-off approval (MSG7)."""
    _require_state(session_id, LegislativeState.AWAITING_APPROVAL)

    if not body.proposer_signature:
        raise HTTPException(400, "Missing proposer signature")
    if not body.regulator_signature:
        raise HTTPException(400, "Missing regulator signature")

    speaker = _speaker()
    speaker_sig = speaker.issue_approval(session_id, body.spec_id)
    if speaker_sig.get("error"):
        raise HTTPException(400, speaker_sig["error"])

    # Log MSG7
    msg7 = LegislativeApproval(
        session_id=session_id,
        spec_id=body.spec_id,
        speaker_signature=speaker_sig["speaker_signature"],
        regulator_signature=body.regulator_signature,
    )
    log_message(_get_db(), session_id, msg7, sender_did="system")

    # Transition to DEPLOYED
    sm = LegislativeStateMachine(session_id, _get_db())
    result = sm.transition(
        LegislativeState.DEPLOYED,
        signatures={
            "proposer": body.proposer_signature,
            "regulator": body.regulator_signature,
        },
    )
    if not result.allowed:
        raise HTTPException(409, result.reason)

    return {
        "session_id": session_id,
        "state": LegislativeState.DEPLOYED.value,
        "spec_id": body.spec_id,
    }


@router.get("/sessions/{session_id}/deployment")
async def get_deployment_status(session_id: str):
    """Get deployment status for a session."""
    conn = _connect()
    try:
        row = conn.execute(
            "SELECT * FROM legislative_session WHERE session_id = ?",
            (session_id,),
        ).fetchone()
    finally:
        conn.close()
    if row is None:
        raise HTTPException(404, f"Session not found: {session_id}")

    deployed = row["state"] == LegislativeState.DEPLOYED.value

    # Get spec if exists
    conn = _connect()
    try:
        spec = conn.execute(
            "SELECT spec_id, status FROM contract_spec "
            "WHERE session_id = ? AND status = 'validated' "
            "ORDER BY created_at DESC LIMIT 1",
            (session_id,),
        ).fetchone()
    finally:
        conn.close()

    return {
        "session_id": session_id,
        "state": row["state"],
        "deployed": deployed,
        "spec_id": spec["spec_id"] if spec else None,
    }


# ========================= P8.10 Constitution & agents ======================

@router.get("/constitution")
async def get_constitution():
    """Get constitutional parameters."""
    conn = _connect()
    try:
        rows = conn.execute(
            "SELECT param_name, param_value, param_type, description "
            "FROM constitution ORDER BY param_name"
        ).fetchall()
    finally:
        conn.close()
    return {
        "parameters": [
            {
                "param_name": r["param_name"],
                "param_value": r["param_value"],
                "param_type": r["param_type"],
                "description": r["description"],
            }
            for r in rows
        ]
    }


@router.get("/agents")
async def list_agents():
    """List all registered agents."""
    conn = _connect()
    try:
        rows = conn.execute(
            "SELECT agent_did, agent_type, display_name, reputation_score, active "
            "FROM agent_registry ORDER BY agent_did"
        ).fetchall()
    finally:
        conn.close()
    return {
        "agents": [
            {
                "agent_did": r["agent_did"],
                "agent_type": r["agent_type"],
                "display_name": r["display_name"],
                "reputation_score": r["reputation_score"],
                "active": bool(r["active"]),
            }
            for r in rows
        ]
    }


@router.get("/agents/{agent_did}/reputation")
async def get_reputation(agent_did: str):
    """Get reputation history for an agent."""
    conn = _connect()
    try:
        agent = conn.execute(
            "SELECT agent_did, reputation_score FROM agent_registry WHERE agent_did = ?",
            (agent_did,),
        ).fetchone()
        if agent is None:
            raise HTTPException(404, f"Agent not found: {agent_did}")

        history = conn.execute(
            "SELECT old_score, new_score, performance_score, reason, created_at "
            "FROM reputation_ledger WHERE agent_did = ? ORDER BY entry_id",
            (agent_did,),
        ).fetchall()
    finally:
        conn.close()

    return {
        "agent_did": agent_did,
        "current_score": agent["reputation_score"],
        "history": [
            {
                "old_score": h["old_score"],
                "new_score": h["new_score"],
                "performance_score": h["performance_score"],
                "reason": h["reason"],
                "created_at": h["created_at"],
            }
            for h in history
        ],
    }
