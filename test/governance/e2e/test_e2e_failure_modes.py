"""E2E failure mode tests — each failure path through the legislative pipeline."""
from __future__ import annotations

import json
import sqlite3
import uuid

import pytest

from oasis.governance.clerks.codifier import Codifier
from oasis.governance.clerks.registrar import Registrar
from oasis.governance.clerks.regulator import Regulator
from oasis.governance.clerks.speaker import Speaker
from oasis.governance.messages import (
    DAGProposal,
    IdentityAttestation,
    TaskBid,
)
from oasis.governance.state_machine import LegislativeState, LegislativeStateMachine


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _create_session(db_path, sid=None, budget=1000.0):
    sid = sid or f"fail-{uuid.uuid4().hex[:8]}"
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute(
        "INSERT INTO legislative_session (session_id, state, epoch, mission_budget_cap) "
        "VALUES (?, 'SESSION_INIT', 0, ?)",
        (sid, budget),
    )
    conn.commit()
    conn.close()
    return sid


def _advance_to_identity(db_path, sid, producers, min_rep=0.1):
    """Advance to IDENTITY_VERIFICATION and attest all producers."""
    db = str(db_path)
    registrar = Registrar(db_path=db, clerk_did="did:oasis:clerk-registrar")
    registrar.open_session(sid, min_rep)
    sm = LegislativeStateMachine(sid, db)
    r = sm.transition(LegislativeState.IDENTITY_VERIFICATION)
    assert r.allowed

    for p in producers:
        att = IdentityAttestation(
            session_id=sid,
            agent_did=p["agent_did"],
            signature="sig",
            reputation_score=p["reputation_score"],
            agent_type="producer",
        )
        registrar.verify_identity(att)

    # Guard: IdentityVerificationResponse
    conn = sqlite3.connect(db)
    conn.execute("PRAGMA foreign_keys = ON")
    for p in producers:
        conn.execute(
            "INSERT INTO message_log "
            "(session_id, msg_type, sender_did, payload) "
            "VALUES (?, 'IdentityVerificationResponse', ?, '{}')",
            (sid, p["agent_did"]),
        )
    conn.commit()
    conn.close()
    return sm


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestFailureModes:
    """Six failure-path tests."""

    def test_agent_below_reputation_floor(self, e2e_db, producers):
        """Agent below reputation floor → FAILED at IDENTITY_VERIFICATION."""
        sid = _create_session(e2e_db)
        db = str(e2e_db)

        # Set reputation floor high
        conn = sqlite3.connect(db)
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute(
            "UPDATE constitution SET param_value = 0.9 "
            "WHERE param_name = 'reputation_floor'"
        )
        conn.commit()
        conn.close()

        registrar = Registrar(db_path=db, clerk_did="did:oasis:clerk-registrar")
        registrar.open_session(sid, min_reputation=0.9)
        sm = LegislativeStateMachine(sid, db)
        r = sm.transition(LegislativeState.IDENTITY_VERIFICATION)
        assert r.allowed

        # Attest a producer with low reputation
        att = IdentityAttestation(
            session_id=sid,
            agent_did=producers[0]["agent_did"],
            signature="sig",
            reputation_score=0.5,  # below 0.9
            agent_type="producer",
        )
        res = registrar.verify_identity(att)
        assert not res["passed"]
        assert any("below" in e.lower() or "reputation" in e.lower() for e in res["errors"])

        # Transition to FAILED
        r = sm.transition(LegislativeState.FAILED, reason="Agent below reputation floor")
        assert r.allowed
        assert sm.current_state == LegislativeState.FAILED

    def test_cyclic_dag_fails_at_proposal(self, e2e_db, producers):
        """Cyclic DAG → FAILED at PROPOSAL_OPEN."""
        sid = _create_session(e2e_db)
        sm = _advance_to_identity(e2e_db, sid, producers)

        r = sm.transition(LegislativeState.PROPOSAL_OPEN)
        assert r.allowed

        cyclic_dag = {
            "nodes": [
                {"node_id": "a", "label": "A", "service_id": "svc-a",
                 "pop_tier": 1, "token_budget": 100.0, "timeout_ms": 60000},
                {"node_id": "b", "label": "B", "service_id": "svc-b",
                 "pop_tier": 1, "token_budget": 100.0, "timeout_ms": 60000},
            ],
            "edges": [
                {"from_node_id": "a", "to_node_id": "b"},
                {"from_node_id": "b", "to_node_id": "a"},
            ],
        }

        speaker = Speaker(db_path=str(e2e_db), clerk_did="did:oasis:clerk-speaker")
        proposal = DAGProposal(
            session_id=sid,
            proposer_did=producers[0]["agent_did"],
            dag_spec=cyclic_dag,
            rationale="Cyclic test",
            token_budget_total=200.0,
            deadline_ms=60000,
        )
        res = speaker.receive_proposal(sid, proposal)
        assert not res["passed"]
        assert any("cycle" in e.lower() for e in res["errors"])

        r = sm.transition(LegislativeState.FAILED, reason="Cyclic DAG")
        assert r.allowed
        assert sm.current_state == LegislativeState.FAILED

    def test_uncovered_nodes_fails_at_bidding(self, e2e_db, producers):
        """Uncovered task nodes at timeout → FAILED at BIDDING_OPEN."""
        sid = _create_session(e2e_db)
        sm = _advance_to_identity(e2e_db, sid, producers)

        r = sm.transition(LegislativeState.PROPOSAL_OPEN)
        assert r.allowed

        dag = {
            "nodes": [
                {"node_id": "n1", "label": "T1", "service_id": "s1",
                 "pop_tier": 1, "token_budget": 500.0, "timeout_ms": 60000},
                {"node_id": "n2", "label": "T2", "service_id": "s2",
                 "pop_tier": 1, "token_budget": 200.0, "timeout_ms": 60000},
            ],
            "edges": [{"from_node_id": "n1", "to_node_id": "n2"}],
        }

        speaker = Speaker(db_path=str(e2e_db), clerk_did="did:oasis:clerk-speaker")
        proposal = DAGProposal(
            session_id=sid, proposer_did=producers[0]["agent_did"],
            dag_spec=dag, rationale="Bid test", token_budget_total=700.0,
            deadline_ms=60000,
        )
        res = speaker.receive_proposal(sid, proposal)
        assert res["passed"]

        r = sm.transition(LegislativeState.BIDDING_OPEN)
        assert r.allowed

        # Only bid on n1, leave n2 uncovered
        regulator = Regulator(db_path=str(e2e_db), clerk_did="did:oasis:clerk-regulator")
        bid = TaskBid(
            session_id=sid, task_node_id="n1",
            bidder_did=producers[0]["agent_did"], service_id="s1",
            proposed_code_hash="abcdef1234567890", stake_amount=0.5,
            estimated_latency_ms=5000, pop_tier_acceptance=1,
        )
        regulator.receive_bid(sid, bid)

        # Cannot transition because n2 is uncovered
        r = sm.can_transition(LegislativeState.REGULATORY_REVIEW)
        assert not r.allowed
        assert "uncovered" in r.reason.lower() or "n2" in r.reason.lower()

        r = sm.transition(LegislativeState.FAILED, reason="Uncovered nodes at timeout")
        assert r.allowed
        assert sm.current_state == LegislativeState.FAILED

    def test_budget_exceeds_cap_fails_at_codification(self, e2e_db, producers):
        """Budget exceeds cap → FAILED at CODIFICATION (constitutional violation)."""
        sid = _create_session(e2e_db, budget=2000000.0)
        sm = _advance_to_identity(e2e_db, sid, producers)

        r = sm.transition(LegislativeState.PROPOSAL_OPEN)
        assert r.allowed

        # Budget cap is 1_000_000 but node budgets will total 1_500_000
        big_dag = {
            "nodes": [
                {"node_id": "big-root", "label": "Root", "service_id": "svc-root",
                 "pop_tier": 1, "token_budget": 1500000.0, "timeout_ms": 60000},
                {"node_id": "big-leaf", "label": "Leaf", "service_id": "svc-leaf",
                 "pop_tier": 1, "token_budget": 500000.0, "timeout_ms": 60000},
            ],
            "edges": [{"from_node_id": "big-root", "to_node_id": "big-leaf"}],
        }

        speaker = Speaker(db_path=str(e2e_db), clerk_did="did:oasis:clerk-speaker")
        # Set budget high enough to pass proposal guard but over constitutional cap
        proposal = DAGProposal(
            session_id=sid, proposer_did=producers[0]["agent_did"],
            dag_spec=big_dag, rationale="Over budget",
            token_budget_total=999999.0,  # under cap at proposal level
            deadline_ms=60000,
        )
        res = speaker.receive_proposal(sid, proposal)
        assert res["passed"]
        proposal_id = res["proposal_id"]

        r = sm.transition(LegislativeState.BIDDING_OPEN)
        assert r.allowed

        regulator = Regulator(db_path=str(e2e_db), clerk_did="did:oasis:clerk-regulator")
        for node in big_dag["nodes"]:
            bid = TaskBid(
                session_id=sid, task_node_id=node["node_id"],
                bidder_did=producers[0]["agent_did"],
                service_id=node["service_id"],
                proposed_code_hash="abcdef1234567890", stake_amount=0.5,
                estimated_latency_ms=5000, pop_tier_acceptance=1,
            )
            regulator.receive_bid(sid, bid)

        r = sm.transition(LegislativeState.REGULATORY_REVIEW)
        assert r.allowed

        regulator.evaluate_bids(sid)
        r = sm.transition(LegislativeState.CODIFICATION)
        assert r.allowed

        # Compile spec — constitutional validation should fail on budget
        conn = sqlite3.connect(str(e2e_db))
        conn.execute("PRAGMA foreign_keys = ON")
        conn.row_factory = sqlite3.Row
        bids = conn.execute(
            "SELECT * FROM bid WHERE session_id = ? AND status = 'approved'",
            (sid,),
        ).fetchall()
        conn.close()

        codifier = Codifier(db_path=str(e2e_db), clerk_did="did:oasis:clerk-codifier")
        spec = codifier.compile_spec(sid, proposal, [dict(b) for b in bids])
        val_result = codifier.run_constitutional_validation(spec)
        assert not val_result.passed
        assert any("budget" in e.message.lower() for e in val_result.errors)

        r = sm.transition(LegislativeState.FAILED, reason="Constitutional budget violation")
        assert r.allowed
        assert sm.current_state == LegislativeState.FAILED

    def test_approval_timeout_fails(self, e2e_db, producers):
        """Approval timeout → FAILED at AWAITING_APPROVAL."""
        from .conftest import drive_session_to_deployed, DEFAULT_DAG

        sid = f"timeout-{uuid.uuid4().hex[:8]}"
        db = str(e2e_db)

        # Drive session up to AWAITING_APPROVAL manually
        registrar = Registrar(db_path=db, clerk_did="did:oasis:clerk-registrar")
        speaker = Speaker(db_path=db, clerk_did="did:oasis:clerk-speaker")
        regulator_clerk = Regulator(db_path=db, clerk_did="did:oasis:clerk-regulator")
        codifier = Codifier(db_path=db, clerk_did="did:oasis:clerk-codifier")

        conn = sqlite3.connect(db)
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute(
            "INSERT INTO legislative_session (session_id, state, epoch, mission_budget_cap) "
            "VALUES (?, 'SESSION_INIT', 0, 1000.0)",
            (sid,),
        )
        conn.commit()
        conn.close()

        sm = LegislativeStateMachine(sid, db)
        registrar.open_session(sid, 0.1)
        sm.transition(LegislativeState.IDENTITY_VERIFICATION)

        for p in producers:
            att = IdentityAttestation(
                session_id=sid, agent_did=p["agent_did"],
                signature="sig", reputation_score=0.5, agent_type="producer",
            )
            registrar.verify_identity(att)

        conn = sqlite3.connect(db)
        conn.execute("PRAGMA foreign_keys = ON")
        for p in producers:
            conn.execute(
                "INSERT INTO message_log (session_id, msg_type, sender_did, payload) "
                "VALUES (?, 'IdentityVerificationResponse', ?, '{}')",
                (sid, p["agent_did"]),
            )
        conn.commit()
        conn.close()

        sm.transition(LegislativeState.PROPOSAL_OPEN)

        dag = DEFAULT_DAG
        proposal = DAGProposal(
            session_id=sid, proposer_did=producers[0]["agent_did"],
            dag_spec=dag, rationale="timeout test",
            token_budget_total=1000.0, deadline_ms=60000,
        )
        speaker.receive_proposal(sid, proposal)
        sm.transition(LegislativeState.BIDDING_OPEN)

        for idx, node in enumerate(dag["nodes"]):
            bid = TaskBid(
                session_id=sid, task_node_id=node["node_id"],
                bidder_did=producers[idx % len(producers)]["agent_did"],
                service_id=node["service_id"],
                proposed_code_hash="abcdef1234567890", stake_amount=0.5,
                estimated_latency_ms=5000, pop_tier_acceptance=1,
            )
            regulator_clerk.receive_bid(sid, bid)

        sm.transition(LegislativeState.REGULATORY_REVIEW)
        regulator_clerk.evaluate_bids(sid)
        sm.transition(LegislativeState.CODIFICATION)

        conn = sqlite3.connect(db)
        conn.execute("PRAGMA foreign_keys = ON")
        conn.row_factory = sqlite3.Row
        bids = conn.execute(
            "SELECT * FROM bid WHERE session_id = ? AND status = 'approved'",
            (sid,),
        ).fetchall()
        conn.close()

        spec = codifier.compile_spec(sid, proposal, [dict(b) for b in bids])
        codifier.run_constitutional_validation(spec)
        sm.transition(LegislativeState.AWAITING_APPROVAL)
        assert sm.current_state == LegislativeState.AWAITING_APPROVAL

        # Simulate timeout by transitioning to FAILED
        r = sm.transition(LegislativeState.FAILED, reason="Approval timeout")
        assert r.allowed
        assert sm.current_state == LegislativeState.FAILED

    def test_reproposal_exhausted_fails(self, e2e_db, producers):
        """Re-proposal exhausted (max 2) → FAILED."""
        sid = _create_session(e2e_db)
        sm = _advance_to_identity(e2e_db, sid, producers)
        db = str(e2e_db)

        speaker = Speaker(db_path=db, clerk_did="did:oasis:clerk-speaker")
        regulator = Regulator(db_path=db, clerk_did="did:oasis:clerk-regulator")

        round_counter = [0]
        all_node_ids = []  # track all node IDs across rounds

        def _make_dag(round_num):
            return {
                "nodes": [
                    {"node_id": f"rp{round_num}-r1", "label": "T", "service_id": "svc",
                     "pop_tier": 1, "token_budget": 500.0, "timeout_ms": 60000},
                    {"node_id": f"rp{round_num}-r2", "label": "T2", "service_id": "svc2",
                     "pop_tier": 1, "token_budget": 200.0, "timeout_ms": 60000},
                ],
                "edges": [{"from_node_id": f"rp{round_num}-r1", "to_node_id": f"rp{round_num}-r2"}],
            }

        def do_proposal_bid_regulatory():
            """Run through proposal → bidding → regulatory."""
            round_counter[0] += 1
            dag = _make_dag(round_counter[0])
            current_nodes = [(n["node_id"], n["service_id"]) for n in dag["nodes"]]
            all_node_ids.extend(current_nodes)

            r = sm.transition(LegislativeState.PROPOSAL_OPEN)
            assert r.allowed

            proposal = DAGProposal(
                session_id=sid, proposer_did=producers[0]["agent_did"],
                dag_spec=dag, rationale=f"re-prop test {round_counter[0]}",
                token_budget_total=700.0, deadline_ms=60000,
            )
            speaker.receive_proposal(sid, proposal)

            r = sm.transition(LegislativeState.BIDDING_OPEN)
            assert r.allowed

            # Bid on ALL node IDs ever created (guard checks all proposals)
            for idx, (node_id, svc_id) in enumerate(all_node_ids):
                bid = TaskBid(
                    session_id=sid, task_node_id=node_id,
                    bidder_did=producers[idx % len(producers)]["agent_did"],
                    service_id=svc_id,
                    proposed_code_hash="abcdef1234567890", stake_amount=0.5,
                    estimated_latency_ms=5000, pop_tier_acceptance=1,
                )
                regulator.receive_bid(sid, bid)

            r = sm.transition(LegislativeState.REGULATORY_REVIEW)
            assert r.allowed
            regulator.evaluate_bids(sid)

        # First round: PROPOSAL_OPEN → BIDDING → REGULATORY
        do_proposal_bid_regulatory()

        # Re-proposal 1: REGULATORY_REVIEW → back to beginning
        do_proposal_bid_regulatory()

        # Re-proposal 2: REGULATORY_REVIEW → back to beginning
        do_proposal_bid_regulatory()

        # Re-proposal 3 should be blocked (max 2 re-proposals)
        r = sm.can_transition(LegislativeState.PROPOSAL_OPEN)
        assert not r.allowed
        assert "max" in r.reason.lower() or "re-proposal" in r.reason.lower()

        # Fail the session
        r = sm.transition(LegislativeState.FAILED, reason="Re-proposal limit exhausted")
        assert r.allowed
        assert sm.current_state == LegislativeState.FAILED
