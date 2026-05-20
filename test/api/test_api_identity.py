"""P8.2 — Identity API tests."""

from __future__ import annotations


def test_request_verification(client, registered_producers):
    """POST identity/request transitions to IDENTITY_VERIFICATION."""
    resp = client.post(
        "/api/governance/sessions",
        json={"mission_budget_cap": 500.0},
    )
    session_id = resp.json()["session_id"]

    resp = client.post(
        f"/api/governance/sessions/{session_id}/identity/request",
        json={"min_reputation": 0.1},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["state"] == "IDENTITY_VERIFICATION"


def test_submit_attestation(client, registered_producers):
    """POST identity/attest verifies a valid attestation."""
    resp = client.post(
        "/api/governance/sessions",
        json={"mission_budget_cap": 500.0},
    )
    session_id = resp.json()["session_id"]

    resp = client.post(
        f"/api/governance/sessions/{session_id}/identity/request",
        json={"min_reputation": 0.1},
    )
    assert resp.status_code == 200

    from oasis.crypto import ed25519
    from oasis.governance.messages import canonical_signed_bytes, IdentityAttestation

    p = registered_producers[0]
    att = IdentityAttestation(
        session_id=session_id,
        agent_did=p["agent_did"],
        signature="ab" * 64,
        reputation_score=0.5,
        agent_type="producer",
    )
    sig_hex = ed25519.sign(p["private_key"], canonical_signed_bytes(att)).hex()

    resp = client.post(
        f"/api/governance/sessions/{session_id}/identity/attest",
        json={
            "agent_did": p["agent_did"],
            "signature": sig_hex,
            "reputation_score": 0.5,
            "agent_type": "producer",
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["passed"] is True


def test_bad_attestation_400(client, registered_producers):
    """POST identity/attest rejects invalid signature."""
    resp = client.post(
        "/api/governance/sessions",
        json={"mission_budget_cap": 500.0},
    )
    session_id = resp.json()["session_id"]

    resp = client.post(
        f"/api/governance/sessions/{session_id}/identity/request",
        json={"min_reputation": 0.1},
    )
    assert resp.status_code == 200

    # Bad DID format (does not start with did:)
    resp = client.post(
        f"/api/governance/sessions/{session_id}/identity/attest",
        json={
            "agent_did": "bad-format-did",
            "signature": "aa" * 64,
            "reputation_score": 0.5,
            "agent_type": "producer",
        },
    )
    assert resp.status_code == 400


def test_reputation_gate(client, registered_producers):
    """POST identity/attest rejects agent below reputation floor."""
    resp = client.post(
        "/api/governance/sessions",
        json={"mission_budget_cap": 500.0},
    )
    session_id = resp.json()["session_id"]

    resp = client.post(
        f"/api/governance/sessions/{session_id}/identity/request",
        json={"min_reputation": 0.5},
    )
    assert resp.status_code == 200

    # Reputation 0.05 is below min_reputation 0.5
    from oasis.crypto import ed25519
    from oasis.governance.messages import canonical_signed_bytes, IdentityAttestation

    p = registered_producers[0]
    att = IdentityAttestation(
        session_id=session_id,
        agent_did=p["agent_did"],
        signature="ab" * 64,
        reputation_score=0.05,
        agent_type="producer",
    )
    sig_hex = ed25519.sign(p["private_key"], canonical_signed_bytes(att)).hex()

    resp = client.post(
        f"/api/governance/sessions/{session_id}/identity/attest",
        json={
            "agent_did": p["agent_did"],
            "signature": sig_hex,
            "reputation_score": 0.05,
            "agent_type": "producer",
        },
    )
    assert resp.status_code == 400
