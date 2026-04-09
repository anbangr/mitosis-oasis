"""E2E HTTP — full legislative pipeline via FastAPI TestClient."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from oasis.api import app
from oasis.governance import endpoints as gov_ep
from oasis.governance.schema import create_governance_tables, seed_clerks, seed_constitution
from oasis.governance.state_machine import LegislativeState, LegislativeStateMachine


@pytest.fixture()
def http_env(tmp_path: Path):
    """Set up a fresh governance DB + TestClient."""
    db = tmp_path / "http_e2e.db"
    gov_ep.init_governance_db(str(db))

    # Register 5 producers
    conn = sqlite3.connect(str(db))
    conn.execute("PRAGMA foreign_keys = ON")
    for i in range(1, 6):
        conn.execute(
            "INSERT OR IGNORE INTO agent_registry "
            "(agent_did, agent_type, display_name, human_principal, reputation_score) "
            "VALUES (?, 'producer', ?, 'human@example.com', 0.5)",
            (f"did:http:producer-{i}", f"HTTP Producer {i}"),
        )
    conn.commit()
    conn.close()

    client = TestClient(app, raise_server_exceptions=False)
    return {"db": db, "client": client}


def test_full_pipeline_via_http(http_env):
    """Walk the entire legislative pipeline via HTTP endpoints."""
    client = http_env["client"]
    db = http_env["db"]

    # 1. Create session
    resp = client.post(
        "/api/governance/sessions",
        json={"mission_budget_cap": 1000.0, "min_reputation": 0.1},
    )
    assert resp.status_code == 201, resp.text
    session_id = resp.json()["session_id"]

    # 2. Open identity verification
    resp = client.post(
        f"/api/governance/sessions/{session_id}/identity/request",
        json={"min_reputation": 0.1},
    )
    assert resp.status_code == 200, resp.text

    # 3. Attest all 5 producers
    for i in range(1, 6):
        resp = client.post(
            f"/api/governance/sessions/{session_id}/identity/attest",
            json={
                "agent_did": f"did:http:producer-{i}",
                "signature": "http-sig",
                "reputation_score": 0.5,
                "agent_type": "producer",
            },
        )
        assert resp.status_code == 200, resp.text

    # Insert IdentityVerificationResponse for guard
    conn = sqlite3.connect(str(db))
    conn.execute("PRAGMA foreign_keys = ON")
    for i in range(1, 6):
        conn.execute(
            "INSERT INTO message_log (session_id, msg_type, sender_did, payload) "
            "VALUES (?, 'IdentityVerificationResponse', ?, '{}')",
            (session_id, f"did:http:producer-{i}"),
        )
    conn.commit()
    conn.close()

    # Transition to PROPOSAL_OPEN
    sm = LegislativeStateMachine(session_id, str(db))
    r = sm.transition(LegislativeState.PROPOSAL_OPEN)
    assert r.allowed, r.reason

    # 4. Submit proposal
    dag_spec = {
        "nodes": [
            {"node_id": "h1", "label": "Task A", "service_id": "svc-a",
             "pop_tier": 1, "token_budget": 500.0, "timeout_ms": 60000},
            {"node_id": "h2", "label": "Task B", "service_id": "svc-b",
             "pop_tier": 1, "token_budget": 200.0, "timeout_ms": 60000},
        ],
        "edges": [{"from_node_id": "h1", "to_node_id": "h2"}],
    }
    resp = client.post(
        f"/api/governance/sessions/{session_id}/proposals",
        json={
            "proposer_did": "did:http:producer-1",
            "dag_spec": dag_spec,
            "rationale": "HTTP E2E test",
            "token_budget_total": 700.0,
            "deadline_ms": 60000,
        },
    )
    assert resp.status_code == 201, resp.text
    proposal_id = resp.json()["proposal_id"]

    # 5. Transition to BIDDING_OPEN
    r = sm.transition(LegislativeState.BIDDING_OPEN)
    assert r.allowed, r.reason

    # 6. Submit bids
    for node_id, svc, bidder_idx in [("h1", "svc-a", 1), ("h2", "svc-b", 2)]:
        resp = client.post(
            f"/api/governance/sessions/{session_id}/bids",
            json={
                "task_node_id": node_id,
                "bidder_did": f"did:http:producer-{bidder_idx}",
                "service_id": svc,
                "proposed_code_hash": "abcdef1234567890",
                "stake_amount": 0.5,
                "estimated_latency_ms": 5000,
                "pop_tier_acceptance": 1,
            },
        )
        assert resp.status_code == 201, resp.text

    # 7. BIDDING_OPEN → REGULATORY_REVIEW
    r = sm.transition(LegislativeState.REGULATORY_REVIEW)
    assert r.allowed, r.reason

    # 8. Regulatory decision
    resp = client.post(
        f"/api/governance/sessions/{session_id}/regulatory/decision",
        json={"submitter_did": "did:oasis:clerk-regulator"},
    )
    assert resp.status_code == 200, resp.text

    # 9. REGULATORY_REVIEW → CODIFICATION
    r = sm.transition(LegislativeState.CODIFICATION)
    assert r.allowed, r.reason

    # 10. Compile spec
    resp = client.post(
        f"/api/governance/sessions/{session_id}/codification/spec",
        json={"proposal_id": proposal_id},
    )
    assert resp.status_code == 201, resp.text
    spec_id = resp.json()["spec_id"]

    # 11. CODIFICATION → AWAITING_APPROVAL
    r = sm.transition(LegislativeState.AWAITING_APPROVAL)
    assert r.allowed, r.reason

    # 12. Dual sign-off and deploy
    resp = client.post(
        f"/api/governance/sessions/{session_id}/approval",
        json={
            "spec_id": spec_id,
            "proposer_signature": "proposer-sig-http",
            "regulator_signature": "regulator-sig-http",
        },
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["state"] == "DEPLOYED"

    # Verify final state
    resp = client.get(f"/api/governance/sessions/{session_id}")
    assert resp.status_code == 200
    assert resp.json()["state"] == "DEPLOYED"
