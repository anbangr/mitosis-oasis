"""P8.4 — Deliberation API tests."""
from __future__ import annotations


def test_submit_straw_poll(client, session_factory):
    """POST deliberation/straw-poll collects ballots."""
    session_id = session_factory("PROPOSAL_OPEN")

    # Submit two proposals and collect their IDs
    pids = []
    for label in ["A", "B"]:
        dag = {"nodes": [{"node_id": label, "label": label, "service_id": "svc",
                          "pop_tier": 1, "token_budget": 50.0, "timeout_ms": 30000}],
               "edges": []}
        resp = client.post(
            f"/api/governance/sessions/{session_id}/proposals",
            json={"proposer_did": "did:mock:producer-1", "dag_spec": dag,
                  "rationale": label, "token_budget_total": 50.0, "deadline_ms": 30000},
        )
        assert resp.status_code == 201
        pids.append(resp.json()["proposal_id"])

    resp = client.post(
        f"/api/governance/sessions/{session_id}/deliberation/straw-poll",
        json={"ballots": {"did:mock:producer-1": pids,
                          "did:mock:producer-2": list(reversed(pids))}},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["total_votes"] == 2


def test_submit_discussion(client, session_factory):
    """POST deliberation/discuss stores a deliberation message."""
    session_id = session_factory("PROPOSAL_OPEN")

    resp = client.post(
        f"/api/governance/sessions/{session_id}/deliberation/discuss",
        json={
            "agent_did": "did:mock:producer-1",
            "round_number": 1,
            "message": "I support proposal A.",
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["round_number"] == 1


def test_get_summary(client, session_factory):
    """GET deliberation/summary returns round data."""
    session_id = session_factory("PROPOSAL_OPEN")

    # Submit some discussion
    client.post(
        f"/api/governance/sessions/{session_id}/deliberation/discuss",
        json={"agent_did": "did:mock:producer-1", "round_number": 1,
              "message": "Round 1 message"},
    )

    resp = client.get(f"/api/governance/sessions/{session_id}/deliberation/summary")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["rounds"]) >= 1
    assert data["rounds"][0]["round_number"] == 1


def test_round_limit(client, session_factory):
    """POST deliberation/discuss rejects round > max_deliberation_rounds."""
    session_id = session_factory("PROPOSAL_OPEN")

    resp = client.post(
        f"/api/governance/sessions/{session_id}/deliberation/discuss",
        json={
            "agent_did": "did:mock:producer-1",
            "round_number": 4,  # exceeds max of 3
            "message": "This should fail",
        },
    )
    assert resp.status_code == 400


def test_speaking_order(client, session_factory):
    """POST deliberation/discuss returns a speaking order."""
    session_id = session_factory("PROPOSAL_OPEN")

    resp = client.post(
        f"/api/governance/sessions/{session_id}/deliberation/discuss",
        json={
            "agent_did": "did:mock:producer-1",
            "round_number": 1,
            "message": "Order test",
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "speaking_order" in data
