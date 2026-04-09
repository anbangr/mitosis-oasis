"""P8.7 — Regulatory API tests."""
from __future__ import annotations


def test_submit_decision(client, session_factory):
    """POST regulatory/decision evaluates bids."""
    session_id = session_factory("REGULATORY_REVIEW")

    resp = client.post(
        f"/api/governance/sessions/{session_id}/regulatory/decision",
        json={"submitter_did": "did:oasis:clerk-regulator"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "approved_bids" in data
    assert "fairness_score" in data


def test_get_evidence(client, session_factory):
    """GET regulatory/evidence returns evidence briefing."""
    session_id = session_factory("REGULATORY_REVIEW")

    resp = client.get(
        f"/api/governance/sessions/{session_id}/regulatory/evidence",
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "bidder_performance" in data
    assert "published_at" in data


def test_only_regulator_can_submit(client, session_factory):
    """POST regulatory/decision rejects non-regulator submitter."""
    session_id = session_factory("REGULATORY_REVIEW")

    resp = client.post(
        f"/api/governance/sessions/{session_id}/regulatory/decision",
        json={"submitter_did": "did:mock:producer-1"},  # not regulator
    )
    assert resp.status_code == 403
