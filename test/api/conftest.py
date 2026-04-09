"""Shared fixtures for API-level tests.

Provides a FastAPI ``TestClient`` wired to the Mitosis-OASIS app with
an in-memory database, plus governance-specific helpers.
"""
from __future__ import annotations

import json
import sqlite3
import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from oasis.api import app
from oasis.governance import endpoints as gov_ep
from oasis.governance.schema import (
    create_governance_tables,
    seed_clerks,
    seed_constitution,
)


@pytest.fixture()
def gov_db(tmp_path: Path) -> Path:
    """Create a fresh governance database and wire it into the endpoints module."""
    db = tmp_path / "gov_test.db"
    gov_ep.init_governance_db(str(db))
    return db


@pytest.fixture()
def client(gov_db: Path) -> TestClient:
    """Return a synchronous TestClient for the Mitosis-OASIS API.

    The governance database is initialised via the *gov_db* fixture so
    all governance endpoints work without the full platform lifespan.
    """
    # Use TestClient without lifespan to avoid Platform startup
    return TestClient(app, raise_server_exceptions=False)


# ---------------------------------------------------------------------------
# Helper: register producer agents in the governance DB
# ---------------------------------------------------------------------------

SAMPLE_PRODUCERS = [
    {
        "agent_did": f"did:mock:producer-{i}",
        "display_name": f"Producer {i}",
        "reputation_score": 0.5,
    }
    for i in range(1, 6)
]


@pytest.fixture()
def registered_producers(gov_db: Path) -> list[dict]:
    """Insert 5 producer agents into agent_registry and return their info."""
    conn = sqlite3.connect(str(gov_db))
    conn.execute("PRAGMA foreign_keys = ON")
    for p in SAMPLE_PRODUCERS:
        conn.execute(
            "INSERT OR IGNORE INTO agent_registry "
            "(agent_did, agent_type, display_name, human_principal, reputation_score) "
            "VALUES (?, 'producer', ?, ?, 0.5)",
            (p["agent_did"], p["display_name"], f"human@example.com"),
        )
    conn.commit()
    conn.close()
    return list(SAMPLE_PRODUCERS)


# ---------------------------------------------------------------------------
# Helper: create a session and advance to a target state
# ---------------------------------------------------------------------------

@pytest.fixture()
def session_factory(client, registered_producers, gov_db):
    """Return a callable that creates a session and advances it to a state."""

    def _create(target_state: str = "SESSION_INIT") -> str:
        # Create session
        resp = client.post(
            "/api/governance/sessions",
            json={"mission_budget_cap": 1000.0, "min_reputation": 0.1},
        )
        assert resp.status_code == 201, resp.text
        session_id = resp.json()["session_id"]

        if target_state == "SESSION_INIT":
            return session_id

        # → IDENTITY_VERIFICATION
        resp = client.post(
            f"/api/governance/sessions/{session_id}/identity/request",
            json={"min_reputation": 0.1},
        )
        assert resp.status_code == 200, resp.text

        if target_state == "IDENTITY_VERIFICATION":
            return session_id

        # Attest all 5 producers + 3 required clerks
        all_attesters = []
        for p in registered_producers:
            resp = client.post(
                f"/api/governance/sessions/{session_id}/identity/attest",
                json={
                    "agent_did": p["agent_did"],
                    "signature": "valid-sig",
                    "reputation_score": 0.5,
                    "agent_type": "producer",
                },
            )
            assert resp.status_code == 200, resp.text
            all_attesters.append(p["agent_did"])

        for role in ["speaker", "regulator", "codifier"]:
            resp = client.post(
                f"/api/governance/sessions/{session_id}/identity/attest",
                json={
                    "agent_did": f"did:oasis:clerk-{role}",
                    "signature": "clerk-sig",
                    "reputation_score": 0.5,
                    "agent_type": "clerk",
                },
            )
            assert resp.status_code == 200, resp.text

        # The state machine guard checks for 'IdentityVerificationResponse'
        # messages (legacy name).  Insert them so the guard passes.
        conn = sqlite3.connect(str(gov_db))
        conn.execute("PRAGMA foreign_keys = ON")
        for did in all_attesters:
            conn.execute(
                "INSERT INTO message_log "
                "(session_id, msg_type, sender_did, payload) "
                "VALUES (?, 'IdentityVerificationResponse', ?, '{}')",
                (session_id, did),
            )
        conn.commit()
        conn.close()

        # Transition to PROPOSAL_OPEN via state machine
        from oasis.governance.state_machine import LegislativeState, LegislativeStateMachine
        sm = LegislativeStateMachine(session_id, str(gov_db))
        result = sm.transition(LegislativeState.PROPOSAL_OPEN)
        assert result.allowed, result.reason

        if target_state == "PROPOSAL_OPEN":
            return session_id

        # Submit a proposal — root with enough budget, child within budget
        dag_spec = {
            "nodes": [
                {"node_id": "n1", "label": "Task A", "service_id": "svc-a",
                 "pop_tier": 1, "token_budget": 200.0, "timeout_ms": 60000},
                {"node_id": "n2", "label": "Task B", "service_id": "svc-b",
                 "pop_tier": 1, "token_budget": 100.0, "timeout_ms": 60000},
            ],
            "edges": [{"from_node_id": "n1", "to_node_id": "n2"}],
        }
        resp = client.post(
            f"/api/governance/sessions/{session_id}/proposals",
            json={
                "proposer_did": "did:mock:producer-1",
                "dag_spec": dag_spec,
                "rationale": "Test proposal",
                "token_budget_total": 300.0,
                "deadline_ms": 60000,
            },
        )
        assert resp.status_code == 201, resp.text

        # Transition to BIDDING_OPEN
        result = sm.transition(LegislativeState.BIDDING_OPEN)
        assert result.allowed, result.reason

        if target_state == "BIDDING_OPEN":
            return session_id

        # Submit bids for both nodes
        for node_id, svc in [("n1", "svc-a"), ("n2", "svc-b")]:
            resp = client.post(
                f"/api/governance/sessions/{session_id}/bids",
                json={
                    "task_node_id": node_id,
                    "bidder_did": "did:mock:producer-1",
                    "service_id": svc,
                    "proposed_code_hash": "abcdef1234567890",
                    "stake_amount": 0.5,
                    "estimated_latency_ms": 5000,
                    "pop_tier_acceptance": 1,
                },
            )
            assert resp.status_code == 201, resp.text

        # Transition to REGULATORY_REVIEW
        result = sm.transition(LegislativeState.REGULATORY_REVIEW)
        assert result.allowed, result.reason

        if target_state == "REGULATORY_REVIEW":
            return session_id

        # Evaluate bids
        resp = client.post(
            f"/api/governance/sessions/{session_id}/regulatory/decision",
            json={"submitter_did": "did:oasis:clerk-regulator"},
        )
        assert resp.status_code == 200, resp.text

        # Transition to CODIFICATION
        result = sm.transition(LegislativeState.CODIFICATION)
        assert result.allowed, result.reason

        if target_state == "CODIFICATION":
            return session_id

        # Compile and validate spec
        conn = sqlite3.connect(str(gov_db))
        conn.row_factory = sqlite3.Row
        prop_row = conn.execute(
            "SELECT proposal_id FROM proposal WHERE session_id = ?",
            (session_id,),
        ).fetchone()
        conn.close()

        resp = client.post(
            f"/api/governance/sessions/{session_id}/codification/spec",
            json={"proposal_id": prop_row["proposal_id"]},
        )
        assert resp.status_code == 201, resp.text

        # Transition to AWAITING_APPROVAL
        result = sm.transition(LegislativeState.AWAITING_APPROVAL)
        assert result.allowed, result.reason

        if target_state == "AWAITING_APPROVAL":
            return session_id

        return session_id

    return _create
