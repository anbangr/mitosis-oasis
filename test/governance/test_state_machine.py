"""P2 — Test LegislativeStateMachine: transitions, guards, history, timeouts."""
import json
import sqlite3
from pathlib import Path

import pytest

from oasis.governance.schema import (
    create_governance_tables,
    seed_clerks,
    seed_constitution,
)
from oasis.governance.state_machine import (
    GuardResult,
    LegislativeState,
    LegislativeStateMachine,
    TimeoutConfig,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _init_db(db_path: Path) -> Path:
    """Create tables + seeds."""
    create_governance_tables(db_path)
    seed_constitution(db_path)
    seed_clerks(db_path)
    return db_path


def _connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA foreign_keys = ON")
    conn.row_factory = sqlite3.Row
    return conn


def _register_producers(db_path: Path, n: int = 5) -> list[str]:
    """Register n producer agents, return their DIDs."""
    conn = _connect(db_path)
    dids = []
    for i in range(1, n + 1):
        did = f"did:mock:p-{i}"
        conn.execute(
            "INSERT OR IGNORE INTO agent_registry "
            "(agent_did, agent_type, display_name, reputation_score) "
            "VALUES (?, 'producer', ?, 0.5)",
            (did, f"Producer {i}"),
        )
        dids.append(did)
    conn.commit()
    conn.close()
    return dids


def _attest_agents(db_path: Path, session_id: str, dids: list[str]) -> None:
    """Insert IdentityVerificationResponse messages for given agents."""
    conn = _connect(db_path)
    for did in dids:
        conn.execute(
            "INSERT INTO message_log (session_id, msg_type, sender_did) "
            "VALUES (?, 'IdentityVerificationResponse', ?)",
            (session_id, did),
        )
    conn.commit()
    conn.close()


def _submit_proposal(db_path: Path, session_id: str, proposer_did: str,
                     budget: float = 500.0) -> str:
    """Insert a proposal with a simple 2-node DAG, return proposal_id."""
    pid = f"prop-{session_id}-1"
    conn = _connect(db_path)
    conn.execute(
        "INSERT INTO proposal "
        "(proposal_id, session_id, proposer_did, dag_spec, token_budget_total, deadline_ms) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (pid, session_id, proposer_did, '{"nodes":[]}', budget, 60000),
    )
    # Add two dag_nodes
    for i, label in enumerate(["Task A", "Task B"]):
        conn.execute(
            "INSERT INTO dag_node "
            "(node_id, proposal_id, label, pop_tier, token_budget, timeout_ms) "
            "VALUES (?, ?, ?, 1, ?, 30000)",
            (f"node-{i}", pid, label, budget / 2),
        )
    conn.commit()
    conn.close()
    return pid


def _submit_bids(db_path: Path, session_id: str, bidder_did: str) -> None:
    """Insert bids for all dag_nodes in the session."""
    conn = _connect(db_path)
    nodes = conn.execute(
        "SELECT dn.node_id FROM dag_node dn "
        "INNER JOIN proposal p ON dn.proposal_id = p.proposal_id "
        "WHERE p.session_id = ?",
        (session_id,),
    ).fetchall()
    for i, node in enumerate(nodes):
        conn.execute(
            "INSERT INTO bid "
            "(bid_id, session_id, task_node_id, bidder_did, stake_amount) "
            "VALUES (?, ?, ?, ?, 10.0)",
            (f"bid-{i}", session_id, node["node_id"], bidder_did),
        )
    conn.commit()
    conn.close()


def _add_regulatory_decision(db_path: Path, session_id: str,
                              critical: bool = False) -> None:
    """Insert a regulatory decision."""
    flags = [{"severity": "CRITICAL", "msg": "bad"}] if critical else []
    conn = _connect(db_path)
    conn.execute(
        "INSERT INTO regulatory_decision "
        "(decision_id, session_id, fairness_score, compliance_flags) "
        "VALUES (?, ?, 0.8, ?)",
        (f"dec-{session_id}", session_id, json.dumps(flags)),
    )
    conn.commit()
    conn.close()


def _add_contract_spec(db_path: Path, session_id: str,
                       status: str = "validated") -> None:
    """Insert a contract spec."""
    conn = _connect(db_path)
    conn.execute(
        "INSERT INTO contract_spec (spec_id, session_id, status) "
        "VALUES (?, ?, ?)",
        (f"spec-{session_id}", session_id, status),
    )
    conn.commit()
    conn.close()


# ---------------------------------------------------------------------------
# Tests: basic init and current_state
# ---------------------------------------------------------------------------

class TestStateMachineInit:

    def test_new_session_starts_at_session_init(self, db_path: Path):
        _init_db(db_path)
        sm = LegislativeStateMachine("sess-1", db_path)
        assert sm.current_state == LegislativeState.SESSION_INIT

    def test_loads_existing_session(self, db_path: Path):
        _init_db(db_path)
        conn = _connect(db_path)
        conn.execute(
            "INSERT INTO legislative_session (session_id, state) "
            "VALUES ('sess-x', 'BIDDING_OPEN')"
        )
        conn.commit()
        conn.close()
        sm = LegislativeStateMachine("sess-x", db_path)
        assert sm.current_state == LegislativeState.BIDDING_OPEN


# ---------------------------------------------------------------------------
# Tests: invalid transitions
# ---------------------------------------------------------------------------

class TestInvalidTransitions:

    def test_init_to_deployed_rejected(self, db_path: Path):
        _init_db(db_path)
        sm = LegislativeStateMachine("sess-inv", db_path)
        result = sm.transition(LegislativeState.DEPLOYED)
        assert not result.allowed

    def test_init_to_bidding_rejected(self, db_path: Path):
        _init_db(db_path)
        sm = LegislativeStateMachine("sess-inv2", db_path)
        result = sm.transition(LegislativeState.BIDDING_OPEN)
        assert not result.allowed

    def test_deployed_is_terminal(self, db_path: Path):
        _init_db(db_path)
        conn = _connect(db_path)
        conn.execute(
            "INSERT INTO legislative_session (session_id, state) "
            "VALUES ('sess-dep', 'DEPLOYED')"
        )
        conn.commit()
        conn.close()
        sm = LegislativeStateMachine("sess-dep", db_path)
        result = sm.transition(LegislativeState.SESSION_INIT)
        assert not result.allowed

    def test_failed_is_terminal(self, db_path: Path):
        _init_db(db_path)
        conn = _connect(db_path)
        conn.execute(
            "INSERT INTO legislative_session (session_id, state) "
            "VALUES ('sess-fail', 'FAILED')"
        )
        conn.commit()
        conn.close()
        sm = LegislativeStateMachine("sess-fail", db_path)
        result = sm.transition(LegislativeState.SESSION_INIT)
        assert not result.allowed

    def test_skip_states_rejected(self, db_path: Path):
        """Cannot skip from SESSION_INIT to REGULATORY_REVIEW."""
        _init_db(db_path)
        sm = LegislativeStateMachine("sess-skip", db_path)
        result = sm.transition(LegislativeState.REGULATORY_REVIEW)
        assert not result.allowed

    def test_backward_transition_rejected(self, db_path: Path):
        """Cannot go from BIDDING_OPEN back to SESSION_INIT."""
        _init_db(db_path)
        conn = _connect(db_path)
        conn.execute(
            "INSERT INTO legislative_session (session_id, state) "
            "VALUES ('sess-back', 'BIDDING_OPEN')"
        )
        conn.commit()
        conn.close()
        sm = LegislativeStateMachine("sess-back", db_path)
        result = sm.transition(LegislativeState.SESSION_INIT)
        assert not result.allowed

    def test_can_transition_matches_transition(self, db_path: Path):
        """can_transition returns the same answer as transition would."""
        _init_db(db_path)
        sm = LegislativeStateMachine("sess-can", db_path)
        can_result = sm.can_transition(LegislativeState.DEPLOYED)
        assert not can_result.allowed

    def test_self_transition_rejected(self, db_path: Path):
        """Cannot transition to the same state."""
        _init_db(db_path)
        sm = LegislativeStateMachine("sess-self", db_path)
        result = sm.transition(LegislativeState.SESSION_INIT)
        assert not result.allowed


# ---------------------------------------------------------------------------
# Tests: guard — identity verification
# ---------------------------------------------------------------------------

class TestGuardIdentity:

    def test_no_producers_blocks_init_to_identity(self, db_path: Path):
        """Cannot advance if no producer agents registered."""
        _init_db(db_path)
        sm = LegislativeStateMachine("sess-noprod", db_path)
        result = sm.transition(LegislativeState.IDENTITY_VERIFICATION)
        assert not result.allowed
        assert "No active producer" in result.reason

    def test_quorum_met_advances(self, db_path: Path):
        _init_db(db_path)
        dids = _register_producers(db_path, 5)
        sm = LegislativeStateMachine("sess-q1", db_path)
        # First: INIT → IDENTITY
        sm.transition(LegislativeState.IDENTITY_VERIFICATION)
        assert sm.current_state == LegislativeState.IDENTITY_VERIFICATION
        # Attest 3 of 5 agents (60% > 51%)
        _attest_agents(db_path, "sess-q1", dids[:3])
        result = sm.transition(LegislativeState.PROPOSAL_OPEN)
        assert result.allowed
        assert sm.current_state == LegislativeState.PROPOSAL_OPEN

    def test_quorum_not_met_blocks(self, db_path: Path):
        _init_db(db_path)
        dids = _register_producers(db_path, 5)
        sm = LegislativeStateMachine("sess-q2", db_path)
        sm.transition(LegislativeState.IDENTITY_VERIFICATION)
        # Attest only 2 of 5 (40% < 51%)
        _attest_agents(db_path, "sess-q2", dids[:2])
        result = sm.transition(LegislativeState.PROPOSAL_OPEN)
        assert not result.allowed
        assert "Quorum not met" in result.reason

    def test_reputation_floor_blocks(self, db_path: Path):
        _init_db(db_path)
        dids = _register_producers(db_path, 3)
        # Set one agent below reputation floor
        conn = _connect(db_path)
        conn.execute(
            "UPDATE agent_registry SET reputation_score = 0.05 "
            "WHERE agent_did = ?", (dids[0],)
        )
        conn.commit()
        conn.close()
        sm = LegislativeStateMachine("sess-rep", db_path)
        sm.transition(LegislativeState.IDENTITY_VERIFICATION)
        _attest_agents(db_path, "sess-rep", dids)  # all 3 attest
        result = sm.transition(LegislativeState.PROPOSAL_OPEN)
        assert not result.allowed
        assert "reputation floor" in result.reason


# ---------------------------------------------------------------------------
# Tests: guard — proposal
# ---------------------------------------------------------------------------

class TestGuardProposal:

    def _advance_to_proposal(self, db_path: Path, session_id: str) -> LegislativeStateMachine:
        _init_db(db_path)
        dids = _register_producers(db_path, 3)
        sm = LegislativeStateMachine(session_id, db_path)
        sm.transition(LegislativeState.IDENTITY_VERIFICATION)
        _attest_agents(db_path, session_id, dids)
        sm.transition(LegislativeState.PROPOSAL_OPEN)
        return sm

    def test_valid_proposal_advances(self, db_path: Path):
        sm = self._advance_to_proposal(db_path, "sess-prop1")
        _submit_proposal(db_path, "sess-prop1", "did:mock:p-1", budget=500.0)
        result = sm.transition(LegislativeState.BIDDING_OPEN)
        assert result.allowed

    def test_no_proposal_blocks(self, db_path: Path):
        sm = self._advance_to_proposal(db_path, "sess-prop2")
        result = sm.transition(LegislativeState.BIDDING_OPEN)
        assert not result.allowed
        assert "No proposals" in result.reason

    def test_over_budget_blocks(self, db_path: Path):
        sm = self._advance_to_proposal(db_path, "sess-prop3")
        _submit_proposal(db_path, "sess-prop3", "did:mock:p-1", budget=2_000_000.0)
        result = sm.transition(LegislativeState.BIDDING_OPEN)
        assert not result.allowed
        assert "budget cap" in result.reason


# ---------------------------------------------------------------------------
# Tests: guard — bidding
# ---------------------------------------------------------------------------

class TestGuardBidding:

    def _advance_to_bidding(self, db_path: Path, session_id: str) -> LegislativeStateMachine:
        _init_db(db_path)
        dids = _register_producers(db_path, 3)
        sm = LegislativeStateMachine(session_id, db_path)
        sm.transition(LegislativeState.IDENTITY_VERIFICATION)
        _attest_agents(db_path, session_id, dids)
        sm.transition(LegislativeState.PROPOSAL_OPEN)
        _submit_proposal(db_path, session_id, dids[0])
        sm.transition(LegislativeState.BIDDING_OPEN)
        return sm

    def test_all_nodes_covered_advances(self, db_path: Path):
        sm = self._advance_to_bidding(db_path, "sess-bid1")
        _submit_bids(db_path, "sess-bid1", "did:mock:p-2")
        result = sm.transition(LegislativeState.REGULATORY_REVIEW)
        assert result.allowed

    def test_uncovered_nodes_blocks(self, db_path: Path):
        sm = self._advance_to_bidding(db_path, "sess-bid2")
        # No bids submitted
        result = sm.transition(LegislativeState.REGULATORY_REVIEW)
        assert not result.allowed
        assert "Uncovered" in result.reason


# ---------------------------------------------------------------------------
# Tests: guard — regulatory
# ---------------------------------------------------------------------------

class TestGuardRegulatory:

    def _advance_to_regulatory(self, db_path: Path, session_id: str) -> LegislativeStateMachine:
        _init_db(db_path)
        dids = _register_producers(db_path, 3)
        sm = LegislativeStateMachine(session_id, db_path)
        sm.transition(LegislativeState.IDENTITY_VERIFICATION)
        _attest_agents(db_path, session_id, dids)
        sm.transition(LegislativeState.PROPOSAL_OPEN)
        _submit_proposal(db_path, session_id, dids[0])
        sm.transition(LegislativeState.BIDDING_OPEN)
        _submit_bids(db_path, session_id, dids[1])
        sm.transition(LegislativeState.REGULATORY_REVIEW)
        return sm

    def test_clean_decision_advances(self, db_path: Path):
        sm = self._advance_to_regulatory(db_path, "sess-reg1")
        _add_regulatory_decision(db_path, "sess-reg1", critical=False)
        result = sm.transition(LegislativeState.CODIFICATION)
        assert result.allowed

    def test_critical_flag_blocks(self, db_path: Path):
        sm = self._advance_to_regulatory(db_path, "sess-reg2")
        _add_regulatory_decision(db_path, "sess-reg2", critical=True)
        result = sm.transition(LegislativeState.CODIFICATION)
        assert not result.allowed
        assert "CRITICAL" in result.reason

    def test_no_decision_blocks(self, db_path: Path):
        sm = self._advance_to_regulatory(db_path, "sess-reg3")
        result = sm.transition(LegislativeState.CODIFICATION)
        assert not result.allowed
        assert "No regulatory decision" in result.reason


# ---------------------------------------------------------------------------
# Tests: guard — codification
# ---------------------------------------------------------------------------

class TestGuardCodification:

    def _advance_to_codification(self, db_path: Path, session_id: str) -> LegislativeStateMachine:
        _init_db(db_path)
        dids = _register_producers(db_path, 3)
        sm = LegislativeStateMachine(session_id, db_path)
        sm.transition(LegislativeState.IDENTITY_VERIFICATION)
        _attest_agents(db_path, session_id, dids)
        sm.transition(LegislativeState.PROPOSAL_OPEN)
        _submit_proposal(db_path, session_id, dids[0])
        sm.transition(LegislativeState.BIDDING_OPEN)
        _submit_bids(db_path, session_id, dids[1])
        sm.transition(LegislativeState.REGULATORY_REVIEW)
        _add_regulatory_decision(db_path, session_id)
        sm.transition(LegislativeState.CODIFICATION)
        return sm

    def test_validated_spec_advances(self, db_path: Path):
        sm = self._advance_to_codification(db_path, "sess-cod1")
        _add_contract_spec(db_path, "sess-cod1", status="validated")
        result = sm.transition(LegislativeState.AWAITING_APPROVAL)
        assert result.allowed

    def test_no_spec_blocks(self, db_path: Path):
        sm = self._advance_to_codification(db_path, "sess-cod2")
        result = sm.transition(LegislativeState.AWAITING_APPROVAL)
        assert not result.allowed
        assert "No contract specification" in result.reason

    def test_draft_spec_blocks(self, db_path: Path):
        sm = self._advance_to_codification(db_path, "sess-cod3")
        _add_contract_spec(db_path, "sess-cod3", status="draft")
        result = sm.transition(LegislativeState.AWAITING_APPROVAL)
        assert not result.allowed
        assert "No validated" in result.reason


# ---------------------------------------------------------------------------
# Tests: guard — approval
# ---------------------------------------------------------------------------

class TestGuardApproval:

    def _advance_to_approval(self, db_path: Path, session_id: str) -> LegislativeStateMachine:
        _init_db(db_path)
        dids = _register_producers(db_path, 3)
        sm = LegislativeStateMachine(session_id, db_path)
        sm.transition(LegislativeState.IDENTITY_VERIFICATION)
        _attest_agents(db_path, session_id, dids)
        sm.transition(LegislativeState.PROPOSAL_OPEN)
        _submit_proposal(db_path, session_id, dids[0])
        sm.transition(LegislativeState.BIDDING_OPEN)
        _submit_bids(db_path, session_id, dids[1])
        sm.transition(LegislativeState.REGULATORY_REVIEW)
        _add_regulatory_decision(db_path, session_id)
        sm.transition(LegislativeState.CODIFICATION)
        _add_contract_spec(db_path, session_id, status="validated")
        sm.transition(LegislativeState.AWAITING_APPROVAL)
        return sm

    def test_dual_signatures_deploy(self, db_path: Path):
        sm = self._advance_to_approval(db_path, "sess-app1")
        result = sm.transition(
            LegislativeState.DEPLOYED,
            signatures={"proposer": "sig-p", "regulator": "sig-r"},
        )
        assert result.allowed
        assert sm.current_state == LegislativeState.DEPLOYED

    def test_missing_signature_blocks(self, db_path: Path):
        sm = self._advance_to_approval(db_path, "sess-app2")
        result = sm.transition(
            LegislativeState.DEPLOYED,
            signatures={"proposer": "sig-p"},  # missing regulator
        )
        assert not result.allowed
        assert "regulator" in result.reason.lower()


# ---------------------------------------------------------------------------
# Tests: happy path (full traversal)
# ---------------------------------------------------------------------------

class TestHappyPath:

    def test_full_session_init_to_deployed(self, db_path: Path):
        """Walk through all 8 states from SESSION_INIT to DEPLOYED."""
        _init_db(db_path)
        dids = _register_producers(db_path, 5)
        sid = "sess-happy"
        sm = LegislativeStateMachine(sid, db_path)

        # 1. SESSION_INIT → IDENTITY_VERIFICATION
        assert sm.transition(LegislativeState.IDENTITY_VERIFICATION).allowed

        # 2. Attest 4/5 agents → PROPOSAL_OPEN
        _attest_agents(db_path, sid, dids[:4])
        assert sm.transition(LegislativeState.PROPOSAL_OPEN).allowed

        # 3. Submit proposal → BIDDING_OPEN
        _submit_proposal(db_path, sid, dids[0], budget=1000.0)
        assert sm.transition(LegislativeState.BIDDING_OPEN).allowed

        # 4. Submit bids → REGULATORY_REVIEW
        _submit_bids(db_path, sid, dids[1])
        assert sm.transition(LegislativeState.REGULATORY_REVIEW).allowed

        # 5. Regulatory decision → CODIFICATION
        _add_regulatory_decision(db_path, sid, critical=False)
        assert sm.transition(LegislativeState.CODIFICATION).allowed

        # 6. Contract spec → AWAITING_APPROVAL
        _add_contract_spec(db_path, sid, status="validated")
        assert sm.transition(LegislativeState.AWAITING_APPROVAL).allowed

        # 7. Dual signatures → DEPLOYED
        result = sm.transition(
            LegislativeState.DEPLOYED,
            signatures={"proposer": "sig-p", "regulator": "sig-r"},
        )
        assert result.allowed
        assert sm.current_state == LegislativeState.DEPLOYED


# ---------------------------------------------------------------------------
# Tests: history
# ---------------------------------------------------------------------------

class TestHistory:

    def test_transitions_logged(self, db_path: Path):
        _init_db(db_path)
        _register_producers(db_path, 3)
        sm = LegislativeStateMachine("sess-hist", db_path)
        sm.transition(LegislativeState.IDENTITY_VERIFICATION)
        history = sm.history()
        assert len(history) == 1
        assert history[0].from_state == LegislativeState.SESSION_INIT
        assert history[0].to_state == LegislativeState.IDENTITY_VERIFICATION

    def test_chronological_order(self, db_path: Path):
        _init_db(db_path)
        dids = _register_producers(db_path, 3)
        sid = "sess-chrono"
        sm = LegislativeStateMachine(sid, db_path)
        sm.transition(LegislativeState.IDENTITY_VERIFICATION)
        _attest_agents(db_path, sid, dids)
        sm.transition(LegislativeState.PROPOSAL_OPEN)
        history = sm.history()
        assert len(history) == 2
        assert history[0].to_state == LegislativeState.IDENTITY_VERIFICATION
        assert history[1].to_state == LegislativeState.PROPOSAL_OPEN


# ---------------------------------------------------------------------------
# Tests: re-proposal
# ---------------------------------------------------------------------------

class TestReproposal:

    def _advance_to_regulatory(self, db_path: Path, session_id: str) -> LegislativeStateMachine:
        _init_db(db_path)
        dids = _register_producers(db_path, 3)
        sm = LegislativeStateMachine(session_id, db_path)
        sm.transition(LegislativeState.IDENTITY_VERIFICATION)
        _attest_agents(db_path, session_id, dids)
        sm.transition(LegislativeState.PROPOSAL_OPEN)
        _submit_proposal(db_path, session_id, dids[0])
        sm.transition(LegislativeState.BIDDING_OPEN)
        _submit_bids(db_path, session_id, dids[1])
        sm.transition(LegislativeState.REGULATORY_REVIEW)
        return sm

    def test_reproposal_allowed(self, db_path: Path):
        sm = self._advance_to_regulatory(db_path, "sess-reprop1")
        result = sm.transition(LegislativeState.PROPOSAL_OPEN)
        assert result.allowed
        assert sm.current_state == LegislativeState.PROPOSAL_OPEN


# ---------------------------------------------------------------------------
# Tests: failure transitions
# ---------------------------------------------------------------------------

class TestFailureTransitions:

    def test_identity_to_failed(self, db_path: Path):
        _init_db(db_path)
        _register_producers(db_path, 3)
        sm = LegislativeStateMachine("sess-f1", db_path)
        sm.transition(LegislativeState.IDENTITY_VERIFICATION)
        result = sm.transition(LegislativeState.FAILED, reason="Timeout")
        assert result.allowed
        assert sm.current_state == LegislativeState.FAILED
        # Check failed_reason stored
        conn = _connect(db_path)
        row = conn.execute(
            "SELECT failed_reason FROM legislative_session WHERE session_id = 'sess-f1'"
        ).fetchone()
        conn.close()
        assert row["failed_reason"] == "Timeout"

    def test_proposal_to_failed(self, db_path: Path):
        _init_db(db_path)
        dids = _register_producers(db_path, 3)
        sm = LegislativeStateMachine("sess-f2", db_path)
        sm.transition(LegislativeState.IDENTITY_VERIFICATION)
        _attest_agents(db_path, "sess-f2", dids)
        sm.transition(LegislativeState.PROPOSAL_OPEN)
        result = sm.transition(LegislativeState.FAILED, reason="No valid proposals")
        assert result.allowed
        assert sm.current_state == LegislativeState.FAILED

    def test_bidding_to_failed(self, db_path: Path):
        _init_db(db_path)
        dids = _register_producers(db_path, 3)
        sm = LegislativeStateMachine("sess-f3", db_path)
        sm.transition(LegislativeState.IDENTITY_VERIFICATION)
        _attest_agents(db_path, "sess-f3", dids)
        sm.transition(LegislativeState.PROPOSAL_OPEN)
        _submit_proposal(db_path, "sess-f3", dids[0])
        sm.transition(LegislativeState.BIDDING_OPEN)
        result = sm.transition(LegislativeState.FAILED, reason="Bidding timeout")
        assert result.allowed
        assert sm.current_state == LegislativeState.FAILED
