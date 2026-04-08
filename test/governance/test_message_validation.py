"""Tests: each MSG_TYPE rejects invalid fields (7 tests)."""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from oasis.governance.messages import (
    CodedContractSpec,
    DAGProposal,
    IdentityAttestation,
    IdentityVerificationRequest,
    LegislativeApproval,
    RegulatoryDecision,
    TaskBid,
)


def test_msg1_rejects_invalid_reputation():
    """min_reputation must be between 0 and 1."""
    with pytest.raises(ValidationError):
        IdentityVerificationRequest(
            session_id="sess-001",
            min_reputation=1.5,
        )


def test_msg2_rejects_missing_signature():
    """signature is required and cannot be empty."""
    with pytest.raises(ValidationError):
        IdentityAttestation(
            session_id="sess-001",
            agent_did="did:mock:producer-1",
            signature="",  # empty string fails min_length=1
            reputation_score=0.5,
            agent_type="producer",
        )


def test_msg3_rejects_dag_without_nodes():
    """dag_spec must contain 'nodes'."""
    with pytest.raises(ValidationError):
        DAGProposal(
            session_id="sess-001",
            proposer_did="did:mock:producer-1",
            dag_spec={"edges": []},  # missing 'nodes'
            rationale="test",
            token_budget_total=100.0,
            deadline_ms=60000,
        )


def test_msg4_rejects_invalid_pop_tier():
    """pop_tier_acceptance must be 1-3."""
    with pytest.raises(ValidationError):
        TaskBid(
            session_id="sess-001",
            task_node_id="node-1",
            bidder_did="did:mock:producer-1",
            service_id="svc-1",
            proposed_code_hash="hash-abc",
            stake_amount=10.0,
            estimated_latency_ms=5000,
            pop_tier_acceptance=5,  # out of range
        )


def test_msg5_rejects_invalid_fairness_score():
    """fairness_score must be between 0 and 1."""
    with pytest.raises(ValidationError):
        RegulatoryDecision(
            session_id="sess-001",
            fairness_score=-0.1,  # negative
            regulatory_signature="sig-xyz",
        )


def test_msg6_rejects_missing_validation_proof():
    """validation_proof is required and cannot be empty."""
    with pytest.raises(ValidationError):
        CodedContractSpec(
            session_id="sess-001",
            collaboration_contract_spec={"type": "multi"},
            guardian_module_spec={"monitor": True},
            verification_module_spec={"method": "hash"},
            gate_module_spec={"gate": "token"},
            service_contract_specs={"svc": {}},
            validation_proof="",  # empty fails min_length=1
        )


def test_msg7_rejects_missing_signatures():
    """Both speaker and regulator signatures are required."""
    with pytest.raises(ValidationError):
        LegislativeApproval(
            session_id="sess-001",
            spec_id="spec-001",
            speaker_signature="",  # empty
            regulator_signature="reg-sig",
        )
