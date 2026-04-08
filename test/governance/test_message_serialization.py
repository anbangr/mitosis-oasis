"""Tests: JSON round-trip, payload integrity, timestamp preservation (3 tests)."""
from __future__ import annotations

import json
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


def test_json_round_trip():
    """All message types survive JSON serialization → deserialization."""
    messages = [
        IdentityVerificationRequest(session_id="s1", min_reputation=0.3),
        IdentityAttestation(
            session_id="s1", agent_did="did:mock:p1", signature="sig",
            reputation_score=0.6, agent_type="producer",
        ),
        DAGProposal(
            session_id="s1", proposer_did="did:mock:p1",
            dag_spec={"nodes": [{"id": "n1"}], "edges": []},
            rationale="test", token_budget_total=100.0, deadline_ms=60000,
        ),
        TaskBid(
            session_id="s1", task_node_id="n1", bidder_did="did:mock:p2",
            service_id="svc1", proposed_code_hash="hash1",
            stake_amount=5.0, estimated_latency_ms=2000, pop_tier_acceptance=1,
        ),
        RegulatoryDecision(
            session_id="s1", approved_bids=["b1"], rejected_bids=[],
            fairness_score=0.9, compliance_flags=[], regulatory_signature="sig-r",
        ),
        CodedContractSpec(
            session_id="s1",
            collaboration_contract_spec={"k": "v"},
            guardian_module_spec={"k": "v"},
            verification_module_spec={"k": "v"},
            gate_module_spec={"k": "v"},
            service_contract_specs={"svc": {}},
            validation_proof="proof",
        ),
        LegislativeApproval(
            session_id="s1", spec_id="spec1",
            speaker_signature="sig-s", regulator_signature="sig-r",
        ),
    ]

    for msg in messages:
        json_str = msg.model_dump_json()
        parsed = json.loads(json_str)
        # Reconstruct from parsed JSON
        rebuilt = type(msg).model_validate(parsed)
        assert rebuilt.session_id == msg.session_id
        assert rebuilt.msg_type == msg.msg_type


def test_payload_integrity():
    """Complex nested payloads (dag_spec, contract specs) survive serialization."""
    dag_spec = {
        "nodes": [
            {"id": "n1", "label": "Root", "budget": 100.0},
            {"id": "n2", "label": "Task A", "budget": 200.0},
        ],
        "edges": [{"from": "n1", "to": "n2"}],
        "metadata": {"version": 1, "tags": ["critical", "ml"]},
    }
    msg = DAGProposal(
        session_id="s1",
        proposer_did="did:mock:p1",
        dag_spec=dag_spec,
        rationale="complex proposal",
        token_budget_total=300.0,
        deadline_ms=120000,
    )

    json_str = msg.model_dump_json()
    parsed = json.loads(json_str)
    rebuilt = DAGProposal.model_validate(parsed)

    assert rebuilt.dag_spec == dag_spec
    assert rebuilt.dag_spec["metadata"]["tags"] == ["critical", "ml"]
    assert rebuilt.dag_spec["nodes"][1]["budget"] == 200.0


def test_timestamp_preservation():
    """Explicit timestamps survive JSON round-trip."""
    ts = datetime(2026, 4, 8, 12, 30, 0, tzinfo=timezone.utc)
    msg = IdentityVerificationRequest(
        session_id="s1",
        min_reputation=0.5,
        timestamp=ts,
    )

    json_str = msg.model_dump_json()
    parsed = json.loads(json_str)
    rebuilt = IdentityVerificationRequest.model_validate(parsed)

    assert rebuilt.timestamp == ts
    assert rebuilt.timestamp.tzinfo is not None
