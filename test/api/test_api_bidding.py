"""P8.6 — Bidding API tests."""
from __future__ import annotations


def test_submit_bid(client, session_factory):
    """POST /bids submits a valid bid."""
    session_id = session_factory("BIDDING_OPEN")

    resp = client.post(
        f"/api/governance/sessions/{session_id}/bids",
        json={
            "task_node_id": "n1",
            "bidder_did": "did:mock:producer-2",
            "service_id": "svc-a",
            "proposed_code_hash": "abcdef1234567890",
            "stake_amount": 0.5,
            "estimated_latency_ms": 5000,
            "pop_tier_acceptance": 1,
        },
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["passed"] is True
    assert data["bid_id"] is not None


def test_list_bids(client, session_factory):
    """GET /bids lists all bids for a session."""
    session_id = session_factory("BIDDING_OPEN")

    # Submit a bid first
    client.post(
        f"/api/governance/sessions/{session_id}/bids",
        json={
            "task_node_id": "n1",
            "bidder_did": "did:mock:producer-3",
            "service_id": "svc-a",
            "proposed_code_hash": "hash12345678",
            "stake_amount": 0.3,
            "estimated_latency_ms": 3000,
            "pop_tier_acceptance": 1,
        },
    )

    resp = client.get(f"/api/governance/sessions/{session_id}/bids")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["bids"]) >= 1


def test_invalid_bid_400(client, session_factory):
    """POST /bids rejects bid with bad code hash."""
    session_id = session_factory("BIDDING_OPEN")

    resp = client.post(
        f"/api/governance/sessions/{session_id}/bids",
        json={
            "task_node_id": "n1",
            "bidder_did": "did:mock:producer-1",
            "service_id": "svc-a",
            "proposed_code_hash": "short",  # too short
            "stake_amount": 0.5,
            "estimated_latency_ms": 5000,
            "pop_tier_acceptance": 1,
        },
    )
    assert resp.status_code == 400


def test_state_gate_bidding(client, session_factory):
    """POST /bids returns 409 when session is not in BIDDING_OPEN."""
    session_id = session_factory("PROPOSAL_OPEN")

    resp = client.post(
        f"/api/governance/sessions/{session_id}/bids",
        json={
            "task_node_id": "n1",
            "bidder_did": "did:mock:producer-1",
            "service_id": "svc-a",
            "proposed_code_hash": "abcdef1234567890",
            "stake_amount": 0.5,
            "estimated_latency_ms": 5000,
            "pop_tier_acceptance": 1,
        },
    )
    assert resp.status_code == 409
