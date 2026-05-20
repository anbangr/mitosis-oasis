"""P8.4 — Deliberation API tests."""

from __future__ import annotations

from oasis.crypto import ed25519
from oasis.governance.messages import DAGProposal, canonical_signed_bytes


def test_submit_straw_poll(client, session_factory, registered_producers):
    """POST deliberation/straw-poll collects ballots."""
    session_id = session_factory("PROPOSAL_OPEN")

    # Submit two proposals and collect their IDs
    pids = []
    proposer = registered_producers[0]
    for label in ["A", "B"]:
        dag = {
            "nodes": [
                {
                    "node_id": label,
                    "label": label,
                    "service_id": "svc",
                    "pop_tier": 1,
                    "token_budget": 50.0,
                    "timeout_ms": 30000,
                }
            ],
            "edges": [],
        }
        proposal = DAGProposal(
            session_id=session_id,
            proposer_did=proposer["agent_did"],
            dag_spec=dag,
            rationale=label,
            token_budget_total=50.0,
            deadline_ms=30000,
        )
        sig = ed25519.sign(
            proposer["private_key"], canonical_signed_bytes(proposal)
        ).hex()
        resp = client.post(
            f"/api/governance/sessions/{session_id}/proposals",
            json={
                "proposer_did": proposer["agent_did"],
                "dag_spec": dag,
                "rationale": label,
                "token_budget_total": 50.0,
                "deadline_ms": 30000,
                "signature": sig,
            },
        )
        assert resp.status_code == 201
        pids.append(resp.json()["proposal_id"])

    resp = client.post(
        f"/api/governance/sessions/{session_id}/deliberation/straw-poll",
        json={
            "ballots": {
                registered_producers[0]["agent_did"]: pids,
                registered_producers[1]["agent_did"]: list(reversed(pids)),
            }
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["total_votes"] == 2


def test_submit_discussion(client, session_factory, registered_producers):
    """POST deliberation/discuss stores a deliberation message."""
    session_id = session_factory("PROPOSAL_OPEN")

    resp = client.post(
        f"/api/governance/sessions/{session_id}/deliberation/discuss",
        json={
            "agent_did": registered_producers[0]["agent_did"],
            "round_number": 1,
            "message": "I support proposal A.",
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["round_number"] == 1


def test_get_summary(client, session_factory, registered_producers):
    """GET deliberation/summary returns round data."""
    session_id = session_factory("PROPOSAL_OPEN")

    # Submit some discussion
    client.post(
        f"/api/governance/sessions/{session_id}/deliberation/discuss",
        json={
            "agent_did": registered_producers[0]["agent_did"],
            "round_number": 1,
            "message": "Round 1 message",
        },
    )

    resp = client.get(f"/api/governance/sessions/{session_id}/deliberation/summary")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["rounds"]) >= 1
    assert data["rounds"][0]["round_number"] == 1


def test_round_limit(client, session_factory, registered_producers):
    """POST deliberation/discuss rejects round > max_deliberation_rounds."""
    session_id = session_factory("PROPOSAL_OPEN")

    resp = client.post(
        f"/api/governance/sessions/{session_id}/deliberation/discuss",
        json={
            "agent_did": registered_producers[0]["agent_did"],
            "round_number": 4,  # exceeds max of 3
            "message": "This should fail",
        },
    )
    assert resp.status_code == 400


def test_speaking_order(client, session_factory, registered_producers):
    """POST deliberation/discuss returns a speaking order."""
    session_id = session_factory("PROPOSAL_OPEN")

    resp = client.post(
        f"/api/governance/sessions/{session_id}/deliberation/discuss",
        json={
            "agent_did": registered_producers[0]["agent_did"],
            "round_number": 1,
            "message": "Order test",
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "speaking_order" in data
