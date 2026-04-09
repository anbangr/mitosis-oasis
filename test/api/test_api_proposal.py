"""P8.3 — Proposal API tests."""
from __future__ import annotations


def test_submit_proposal(client, session_factory):
    """POST proposals submits a valid DAG proposal."""
    session_id = session_factory("PROPOSAL_OPEN")
    dag_spec = {
        "nodes": [
            {"node_id": "a", "label": "Step A", "service_id": "svc",
             "pop_tier": 1, "token_budget": 50.0, "timeout_ms": 30000},
        ],
        "edges": [],
    }
    resp = client.post(
        f"/api/governance/sessions/{session_id}/proposals",
        json={
            "proposer_did": "did:mock:producer-1",
            "dag_spec": dag_spec,
            "rationale": "Test single-node",
            "token_budget_total": 50.0,
            "deadline_ms": 30000,
        },
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["passed"] is True
    assert data["proposal_id"] is not None


def test_get_proposal_details(client, session_factory):
    """GET proposals/{pid} returns stored proposal."""
    session_id = session_factory("PROPOSAL_OPEN")
    dag_spec = {
        "nodes": [
            {"node_id": "x", "label": "X", "service_id": "svc",
             "pop_tier": 1, "token_budget": 100.0, "timeout_ms": 60000},
        ],
        "edges": [],
    }
    resp = client.post(
        f"/api/governance/sessions/{session_id}/proposals",
        json={
            "proposer_did": "did:mock:producer-2",
            "dag_spec": dag_spec,
            "rationale": "Get test",
            "token_budget_total": 100.0,
            "deadline_ms": 60000,
        },
    )
    pid = resp.json()["proposal_id"]

    resp = client.get(f"/api/governance/sessions/{session_id}/proposals/{pid}")
    assert resp.status_code == 200
    assert resp.json()["proposal_id"] == pid


def test_invalid_dag_400(client, session_factory):
    """POST proposals rejects cyclic DAG."""
    session_id = session_factory("PROPOSAL_OPEN")
    dag_spec = {
        "nodes": [
            {"node_id": "a", "label": "A", "service_id": "svc",
             "pop_tier": 1, "token_budget": 50.0, "timeout_ms": 30000},
            {"node_id": "b", "label": "B", "service_id": "svc",
             "pop_tier": 1, "token_budget": 50.0, "timeout_ms": 30000},
        ],
        "edges": [
            {"from_node_id": "a", "to_node_id": "b"},
            {"from_node_id": "b", "to_node_id": "a"},
        ],
    }
    resp = client.post(
        f"/api/governance/sessions/{session_id}/proposals",
        json={
            "proposer_did": "did:mock:producer-1",
            "dag_spec": dag_spec,
            "rationale": "Cyclic test",
            "token_budget_total": 100.0,
            "deadline_ms": 30000,
        },
    )
    assert resp.status_code == 400


def test_budget_exceeded_400(client, session_factory):
    """POST proposals rejects budget exceeding cap."""
    session_id = session_factory("PROPOSAL_OPEN")
    dag_spec = {
        "nodes": [
            {"node_id": "a", "label": "A", "service_id": "svc",
             "pop_tier": 1, "token_budget": 2_000_000.0, "timeout_ms": 30000},
        ],
        "edges": [],
    }
    resp = client.post(
        f"/api/governance/sessions/{session_id}/proposals",
        json={
            "proposer_did": "did:mock:producer-1",
            "dag_spec": dag_spec,
            "rationale": "Over budget",
            "token_budget_total": 2_000_000.0,
            "deadline_ms": 30000,
        },
    )
    assert resp.status_code == 400
