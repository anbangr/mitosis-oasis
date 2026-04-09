"""P8.11 — State gate tests: endpoints reject calls in wrong state (409)."""
from __future__ import annotations


def test_bid_in_proposal_open_409(client, session_factory):
    """Bidding endpoint returns 409 when session is in PROPOSAL_OPEN."""
    session_id = session_factory("PROPOSAL_OPEN")

    resp = client.post(
        f"/api/governance/sessions/{session_id}/bids",
        json={
            "task_node_id": "n1",
            "bidder_did": "did:mock:producer-1",
            "service_id": "svc",
            "proposed_code_hash": "abcdef1234567890",
            "stake_amount": 0.5,
            "estimated_latency_ms": 5000,
            "pop_tier_acceptance": 1,
        },
    )
    assert resp.status_code == 409


def test_proposal_in_bidding_409(client, session_factory):
    """Proposal endpoint returns 409 when session is in BIDDING_OPEN."""
    session_id = session_factory("BIDDING_OPEN")

    resp = client.post(
        f"/api/governance/sessions/{session_id}/proposals",
        json={
            "proposer_did": "did:mock:producer-1",
            "dag_spec": {"nodes": [{"node_id": "x", "label": "X",
                                     "service_id": "s", "pop_tier": 1,
                                     "token_budget": 10.0, "timeout_ms": 1000}],
                         "edges": []},
            "rationale": "Wrong state",
            "token_budget_total": 10.0,
            "deadline_ms": 1000,
        },
    )
    assert resp.status_code == 409


def test_approval_in_codification_409(client, session_factory):
    """Approval endpoint returns 409 when session is in CODIFICATION."""
    session_id = session_factory("CODIFICATION")

    resp = client.post(
        f"/api/governance/sessions/{session_id}/approval",
        json={
            "spec_id": "some-spec",
            "proposer_signature": "sig1",
            "regulator_signature": "sig2",
        },
    )
    assert resp.status_code == 409
