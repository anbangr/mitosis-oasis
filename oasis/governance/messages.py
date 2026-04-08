"""Protocol messages MSG1–MSG7 for the legislative governance pipeline.

Defines Pydantic v2 models for each of the 7 message types exchanged
during a legislative session, plus helpers for validation, logging, and
retrieval.

Message Types
-------------
1. IdentityVerificationRequest (MSG1) — Registrar broadcasts to open ID phase
2. IdentityAttestation          (MSG2) — Agent proves identity & reputation
3. DAGProposal                  (MSG3) — Producer submits a task-DAG proposal
4. TaskBid                      (MSG4) — Producer bids on a task node
5. RegulatoryDecision           (MSG5) — Regulator approves/rejects bid set
6. CodedContractSpec            (MSG6) — Codifier emits deployment spec
7. LegislativeApproval          (MSG7) — Dual-signed final approval
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Optional, Union

from pydantic import BaseModel, Field, field_validator


# ---------------------------------------------------------------------------
# Message type enum
# ---------------------------------------------------------------------------

class MessageType(str, Enum):
    """The 7 protocol message types (§3.4 of the AgentCity paper)."""
    IDENTITY_VERIFICATION_REQUEST = "IDENTITY_VERIFICATION_REQUEST"
    IDENTITY_ATTESTATION = "IDENTITY_ATTESTATION"
    DAG_PROPOSAL = "DAG_PROPOSAL"
    TASK_BID = "TASK_BID"
    REGULATORY_DECISION = "REGULATORY_DECISION"
    CODED_CONTRACT_SPEC = "CODED_CONTRACT_SPEC"
    LEGISLATIVE_APPROVAL = "LEGISLATIVE_APPROVAL"


# ---------------------------------------------------------------------------
# Helper: default timestamp
# ---------------------------------------------------------------------------

def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# MSG1 — IdentityVerificationRequest
# ---------------------------------------------------------------------------

class IdentityVerificationRequest(BaseModel):
    """MSG1: Registrar opens the identity-verification phase."""
    msg_type: MessageType = MessageType.IDENTITY_VERIFICATION_REQUEST
    session_id: str = Field(..., min_length=1)
    min_reputation: float = Field(..., ge=0.0, le=1.0)
    timestamp: datetime = Field(default_factory=_utcnow)


# ---------------------------------------------------------------------------
# MSG2 — IdentityAttestation
# ---------------------------------------------------------------------------

class IdentityAttestation(BaseModel):
    """MSG2: An agent attests its identity and reputation."""
    msg_type: MessageType = MessageType.IDENTITY_ATTESTATION
    session_id: str = Field(..., min_length=1)
    agent_did: str = Field(..., min_length=1)
    signature: str = Field(..., min_length=1)
    reputation_score: float = Field(..., ge=0.0, le=1.0)
    agent_type: str = Field(..., pattern=r"^(producer|clerk)$")
    timestamp: datetime = Field(default_factory=_utcnow)


# ---------------------------------------------------------------------------
# MSG3 — DAGProposal
# ---------------------------------------------------------------------------

class DAGProposal(BaseModel):
    """MSG3: A producer submits a task-DAG proposal."""
    msg_type: MessageType = MessageType.DAG_PROPOSAL
    session_id: str = Field(..., min_length=1)
    proposer_did: str = Field(..., min_length=1)
    dag_spec: dict = Field(...)
    rationale: str = Field(..., min_length=1)
    token_budget_total: float = Field(..., gt=0)
    deadline_ms: int = Field(..., gt=0)
    timestamp: datetime = Field(default_factory=_utcnow)

    @field_validator("dag_spec")
    @classmethod
    def dag_spec_must_have_nodes(cls, v: dict) -> dict:
        if "nodes" not in v:
            raise ValueError("dag_spec must contain 'nodes'")
        return v


# ---------------------------------------------------------------------------
# MSG4 — TaskBid
# ---------------------------------------------------------------------------

class TaskBid(BaseModel):
    """MSG4: A producer bids on a task node."""
    msg_type: MessageType = MessageType.TASK_BID
    session_id: str = Field(..., min_length=1)
    task_node_id: str = Field(..., min_length=1)
    bidder_did: str = Field(..., min_length=1)
    service_id: str = Field(..., min_length=1)
    proposed_code_hash: str = Field(..., min_length=1)
    stake_amount: float = Field(..., ge=0)
    estimated_latency_ms: int = Field(..., gt=0)
    pop_tier_acceptance: int = Field(..., ge=1, le=3)
    timestamp: datetime = Field(default_factory=_utcnow)


# ---------------------------------------------------------------------------
# MSG5 — RegulatoryDecision
# ---------------------------------------------------------------------------

class RegulatoryDecision(BaseModel):
    """MSG5: Regulator's approval/rejection of bid set."""
    msg_type: MessageType = MessageType.REGULATORY_DECISION
    session_id: str = Field(..., min_length=1)
    approved_bids: list[str] = Field(default_factory=list)
    rejected_bids: list[str] = Field(default_factory=list)
    fairness_score: float = Field(..., ge=0.0, le=1.0)
    compliance_flags: list[str] = Field(default_factory=list)
    regulatory_signature: str = Field(..., min_length=1)
    timestamp: datetime = Field(default_factory=_utcnow)


# ---------------------------------------------------------------------------
# MSG6 — CodedContractSpec
# ---------------------------------------------------------------------------

class CodedContractSpec(BaseModel):
    """MSG6: Codifier emits the full deployment specification."""
    msg_type: MessageType = MessageType.CODED_CONTRACT_SPEC
    session_id: str = Field(..., min_length=1)
    collaboration_contract_spec: dict = Field(...)
    guardian_module_spec: dict = Field(...)
    verification_module_spec: dict = Field(...)
    gate_module_spec: dict = Field(...)
    service_contract_specs: dict = Field(...)
    validation_proof: str = Field(..., min_length=1)
    timestamp: datetime = Field(default_factory=_utcnow)


# ---------------------------------------------------------------------------
# MSG7 — LegislativeApproval
# ---------------------------------------------------------------------------

class LegislativeApproval(BaseModel):
    """MSG7: Dual-signed final approval to deploy."""
    msg_type: MessageType = MessageType.LEGISLATIVE_APPROVAL
    session_id: str = Field(..., min_length=1)
    spec_id: str = Field(..., min_length=1)
    speaker_signature: str = Field(..., min_length=1)
    regulator_signature: str = Field(..., min_length=1)
    timestamp: datetime = Field(default_factory=_utcnow)


# ---------------------------------------------------------------------------
# Union type for all protocol messages
# ---------------------------------------------------------------------------

ProtocolMessage = Union[
    IdentityVerificationRequest,
    IdentityAttestation,
    DAGProposal,
    TaskBid,
    RegulatoryDecision,
    CodedContractSpec,
    LegislativeApproval,
]

# Lookup from MessageType enum to model class
MESSAGE_MODELS: dict[MessageType, type[BaseModel]] = {
    MessageType.IDENTITY_VERIFICATION_REQUEST: IdentityVerificationRequest,
    MessageType.IDENTITY_ATTESTATION: IdentityAttestation,
    MessageType.DAG_PROPOSAL: DAGProposal,
    MessageType.TASK_BID: TaskBid,
    MessageType.REGULATORY_DECISION: RegulatoryDecision,
    MessageType.CODED_CONTRACT_SPEC: CodedContractSpec,
    MessageType.LEGISLATIVE_APPROVAL: LegislativeApproval,
}


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def validate_message(msg: ProtocolMessage) -> list[str]:
    """Run type-specific validation on a protocol message.

    Returns a list of error strings (empty if valid).
    """
    errors: list[str] = []

    if isinstance(msg, IdentityVerificationRequest):
        if msg.min_reputation < 0 or msg.min_reputation > 1:
            errors.append("min_reputation must be between 0 and 1")

    elif isinstance(msg, IdentityAttestation):
        if not msg.agent_did.startswith("did:"):
            errors.append("agent_did must start with 'did:'")

    elif isinstance(msg, DAGProposal):
        if "nodes" not in msg.dag_spec:
            errors.append("dag_spec must contain 'nodes'")
        if msg.token_budget_total <= 0:
            errors.append("token_budget_total must be positive")

    elif isinstance(msg, TaskBid):
        if msg.stake_amount < 0:
            errors.append("stake_amount must be non-negative")

    elif isinstance(msg, RegulatoryDecision):
        if msg.fairness_score < 0 or msg.fairness_score > 1:
            errors.append("fairness_score must be between 0 and 1")

    elif isinstance(msg, CodedContractSpec):
        required_specs = [
            "collaboration_contract_spec",
            "guardian_module_spec",
            "verification_module_spec",
            "gate_module_spec",
            "service_contract_specs",
        ]
        for spec_name in required_specs:
            if not getattr(msg, spec_name):
                errors.append(f"{spec_name} must not be empty")

    elif isinstance(msg, LegislativeApproval):
        if not msg.speaker_signature:
            errors.append("speaker_signature is required")
        if not msg.regulator_signature:
            errors.append("regulator_signature is required")

    return errors


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

def log_message(
    db_path: Union[str, Path],
    session_id: str,
    msg: ProtocolMessage,
    sender_did: str = "system",
    receiver: Optional[str] = None,
) -> int:
    """Append a protocol message to the message_log table.

    Returns the log_id of the inserted row.
    """
    payload = msg.model_dump_json()
    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute("PRAGMA foreign_keys = ON")
        cursor = conn.execute(
            "INSERT INTO message_log "
            "(session_id, msg_type, sender_did, receiver, payload) "
            "VALUES (?, ?, ?, ?, ?)",
            (session_id, msg.msg_type.value, sender_did, receiver, payload),
        )
        conn.commit()
        return cursor.lastrowid  # type: ignore[return-value]
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Retrieval
# ---------------------------------------------------------------------------

def get_session_messages(
    db_path: Union[str, Path],
    session_id: str,
    msg_type: Optional[MessageType] = None,
) -> list[dict[str, Any]]:
    """Query protocol messages for a session, optionally filtered by type.

    Returns a list of dicts with keys: log_id, session_id, msg_type,
    sender_did, receiver, payload (parsed), created_at.
    Results are ordered chronologically (ascending).
    """
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        if msg_type is not None:
            rows = conn.execute(
                "SELECT * FROM message_log "
                "WHERE session_id = ? AND msg_type = ? "
                "ORDER BY log_id ASC",
                (session_id, msg_type.value),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM message_log "
                "WHERE session_id = ? "
                "ORDER BY log_id ASC",
                (session_id,),
            ).fetchall()

        results = []
        for row in rows:
            payload_raw = row["payload"]
            try:
                payload = json.loads(payload_raw) if payload_raw else None
            except (json.JSONDecodeError, TypeError):
                payload = payload_raw
            results.append({
                "log_id": row["log_id"],
                "session_id": row["session_id"],
                "msg_type": row["msg_type"],
                "sender_did": row["sender_did"],
                "receiver": row["receiver"],
                "payload": payload,
                "created_at": row["created_at"],
            })
        return results
    finally:
        conn.close()
