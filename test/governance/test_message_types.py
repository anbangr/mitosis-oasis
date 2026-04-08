"""Tests: each MSG_TYPE creates a valid model instance (7 tests)."""
from __future__ import annotations

from datetime import datetime, timezone

from oasis.governance.messages import (
    CodedContractSpec,
    DAGProposal,
    IdentityAttestation,
    IdentityVerificationRequest,
    LegislativeApproval,
    MessageType,
    RegulatoryDecision,
    TaskBid,
)


def test_msg1_identity_verification_request():
    msg = IdentityVerificationRequest(
        session_id="sess-001",
        min_reputation=0.3,
    )
    assert msg.msg_type == MessageType.IDENTITY_VERIFICATION_REQUEST
    assert msg.session_id == "sess-001"
    assert msg.min_reputation == 0.3
    assert isinstance(msg.timestamp, datetime)


def test_msg2_identity_attestation():
    msg = IdentityAttestation(
        session_id="sess-001",
        agent_did="did:mock:producer-1",
        signature="sig-abc123",
        reputation_score=0.75,
        agent_type="producer",
    )
    assert msg.msg_type == MessageType.IDENTITY_ATTESTATION
    assert msg.agent_did == "did:mock:producer-1"
    assert msg.reputation_score == 0.75
    assert msg.agent_type == "producer"


def test_msg3_dag_proposal():
    msg = DAGProposal(
        session_id="sess-001",
        proposer_did="did:mock:producer-1",
        dag_spec={"nodes": [{"id": "n1", "label": "Task A"}], "edges": []},
        rationale="Optimize pipeline throughput",
        token_budget_total=500.0,
        deadline_ms=60000,
    )
    assert msg.msg_type == MessageType.DAG_PROPOSAL
    assert msg.proposer_did == "did:mock:producer-1"
    assert "nodes" in msg.dag_spec
    assert msg.token_budget_total == 500.0


def test_msg4_task_bid():
    msg = TaskBid(
        session_id="sess-001",
        task_node_id="node-1",
        bidder_did="did:mock:producer-2",
        service_id="svc-analyzer",
        proposed_code_hash="sha256:abc123",
        stake_amount=10.0,
        estimated_latency_ms=5000,
        pop_tier_acceptance=2,
    )
    assert msg.msg_type == MessageType.TASK_BID
    assert msg.task_node_id == "node-1"
    assert msg.stake_amount == 10.0
    assert msg.pop_tier_acceptance == 2


def test_msg5_regulatory_decision():
    msg = RegulatoryDecision(
        session_id="sess-001",
        approved_bids=["bid-1", "bid-2"],
        rejected_bids=["bid-3"],
        fairness_score=0.85,
        compliance_flags=["FLAG_A"],
        regulatory_signature="reg-sig-xyz",
    )
    assert msg.msg_type == MessageType.REGULATORY_DECISION
    assert len(msg.approved_bids) == 2
    assert msg.fairness_score == 0.85


def test_msg6_coded_contract_spec():
    msg = CodedContractSpec(
        session_id="sess-001",
        collaboration_contract_spec={"type": "multi-party"},
        guardian_module_spec={"monitor": True},
        verification_module_spec={"method": "hash-check"},
        gate_module_spec={"gate": "token-gate"},
        service_contract_specs={"svc-1": {"endpoint": "/run"}},
        validation_proof="proof-abc123",
    )
    assert msg.msg_type == MessageType.CODED_CONTRACT_SPEC
    assert msg.collaboration_contract_spec["type"] == "multi-party"
    assert msg.validation_proof == "proof-abc123"


def test_msg7_legislative_approval():
    msg = LegislativeApproval(
        session_id="sess-001",
        spec_id="spec-001",
        speaker_signature="speaker-sig-abc",
        regulator_signature="reg-sig-xyz",
    )
    assert msg.msg_type == MessageType.LEGISLATIVE_APPROVAL
    assert msg.spec_id == "spec-001"
    assert msg.speaker_signature == "speaker-sig-abc"
    assert msg.regulator_signature == "reg-sig-xyz"
