"""P8.5 — Voting API tests."""
from __future__ import annotations


def test_submit_ranking(client, session_factory):
    """POST /vote submits valid rankings and returns a winner."""
    session_id = session_factory("PROPOSAL_OPEN")

    # Create two proposals as candidates
    for label in ["X", "Y"]:
        dag = {"nodes": [{"node_id": label, "label": label, "service_id": "svc",
                          "pop_tier": 1, "token_budget": 50.0, "timeout_ms": 30000}],
               "edges": []}
        resp = client.post(
            f"/api/governance/sessions/{session_id}/proposals",
            json={"proposer_did": "did:mock:producer-1", "dag_spec": dag,
                  "rationale": label, "token_budget_total": 50.0, "deadline_ms": 30000},
        )
        assert resp.status_code == 201

    # Get proposal IDs
    import sqlite3
    from oasis.governance.endpoints import _get_db
    conn = sqlite3.connect(_get_db())
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT proposal_id FROM proposal WHERE session_id = ?", (session_id,)
    ).fetchall()
    conn.close()
    candidates = [r["proposal_id"] for r in rows]
    assert len(candidates) >= 2

    resp = client.post(
        f"/api/governance/sessions/{session_id}/vote",
        json={"ballots": {
            "did:mock:producer-1": candidates,
            "did:mock:producer-2": list(reversed(candidates)),
            "did:mock:producer-3": candidates,
        }},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "winner" in data


def test_get_results(client, session_factory):
    """GET /vote/results returns vote data."""
    session_id = session_factory("PROPOSAL_OPEN")

    resp = client.get(f"/api/governance/sessions/{session_id}/vote/results")
    assert resp.status_code == 200
    data = resp.json()
    assert "votes" in data
    assert "total_votes" in data


def test_incomplete_ranking_400(client, session_factory):
    """POST /vote rejects inconsistent rankings."""
    session_id = session_factory("PROPOSAL_OPEN")

    resp = client.post(
        f"/api/governance/sessions/{session_id}/vote",
        json={"ballots": {
            "did:mock:producer-1": ["p1", "p2"],
            "did:mock:producer-2": ["p1"],  # missing p2
        }},
    )
    assert resp.status_code == 400


def test_quorum_check(client, session_factory):
    """POST /vote with one voter still returns result (quorum checked)."""
    session_id = session_factory("PROPOSAL_OPEN")

    resp = client.post(
        f"/api/governance/sessions/{session_id}/vote",
        json={"ballots": {
            "did:mock:producer-1": ["cand-a", "cand-b"],
        }},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "quorum_met" in data
