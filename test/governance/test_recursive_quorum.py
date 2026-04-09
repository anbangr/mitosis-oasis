"""P9 tests — quorum inheritance across session depths."""
from __future__ import annotations

import json
import sqlite3

import pytest

from oasis.governance.dag import trigger_child_session
from oasis.governance.schema import (
    create_governance_tables,
    seed_clerks,
    seed_constitution,
)
from oasis.governance.state_machine import (
    GuardResult,
    LegislativeState,
    LegislativeStateMachine,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _setup_parent_with_dag(db_path, session_id="parent-1"):
    """Create a parent session with a non-leaf DAG node."""
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute(
        "INSERT INTO legislative_session (session_id, state, epoch) "
        "VALUES (?, 'DEPLOYED', 0)",
        (session_id,),
    )
    dag_spec = json.dumps({"nodes": ["root", "A"], "edges": [["root", "A"]]})
    conn.execute(
        "INSERT INTO proposal "
        "(proposal_id, session_id, proposer_did, dag_spec, "
        " token_budget_total, deadline_ms) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        ("prop-q", session_id, "did:oasis:clerk-registrar", dag_spec, 1000.0, 60000),
    )
    for nid, label, budget in [("root-q", "Root", 1000.0), ("A-q", "Task A", 500.0)]:
        conn.execute(
            "INSERT INTO dag_node "
            "(node_id, proposal_id, label, service_id, pop_tier, "
            " token_budget, timeout_ms) "
            "VALUES (?, 'prop-q', ?, 'svc', 1, ?, 60000)",
            (nid, label, budget),
        )
    conn.execute(
        "INSERT INTO dag_edge (proposal_id, from_node_id, to_node_id) "
        "VALUES ('prop-q', 'root-q', 'A-q')"
    )
    conn.commit()
    conn.close()


def _register_producers(db_path, count=5):
    """Register producer agents."""
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA foreign_keys = ON")
    for i in range(1, count + 1):
        conn.execute(
            "INSERT OR IGNORE INTO agent_registry "
            "(agent_did, agent_type, display_name, human_principal, reputation_score) "
            "VALUES (?, 'producer', ?, ?, 0.5)",
            (f"did:mock:producer-{i}", f"Producer {i}", f"human-{i}@example.com"),
        )
    conn.commit()
    conn.close()


def _attest_identity(db_path, session_id, agent_dids):
    """Log IdentityVerificationResponse for agents."""
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA foreign_keys = ON")
    for did in agent_dids:
        conn.execute(
            "INSERT INTO message_log "
            "(session_id, msg_type, sender_did, receiver, payload) "
            "VALUES (?, 'IdentityVerificationResponse', ?, 'session', '{}')",
            (session_id, did),
        )
    conn.commit()
    conn.close()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestRecursiveQuorum:
    """Quorum rules apply identically at all session depths."""

    def test_same_quorum_depth_0_and_1(self, governance_db):
        """Quorum threshold is the same for root and child sessions."""
        _setup_parent_with_dag(governance_db)
        _register_producers(governance_db, 5)

        # Create child session
        child_id = trigger_child_session(
            "parent-1", "root-q", governance_db
        )

        # The child session starts in SESSION_INIT — advance to IDENTITY_VERIFICATION
        sm = LegislativeStateMachine(child_id, governance_db)
        assert sm.current_state == LegislativeState.SESSION_INIT
        result = sm.transition(LegislativeState.IDENTITY_VERIFICATION)
        assert result.allowed

        # Attest 3 of 5 producers (60% > 51% quorum)
        _attest_identity(
            governance_db, child_id,
            [f"did:mock:producer-{i}" for i in range(1, 4)],
        )

        # Transition to PROPOSAL_OPEN should succeed (same quorum rules)
        result = sm.can_transition(LegislativeState.PROPOSAL_OPEN)
        assert result.allowed

    def test_quorum_failure_blocks_at_any_depth(self, governance_db):
        """Quorum failure at child depth blocks transition."""
        _setup_parent_with_dag(governance_db)
        _register_producers(governance_db, 5)

        child_id = trigger_child_session(
            "parent-1", "root-q", governance_db
        )

        sm = LegislativeStateMachine(child_id, governance_db)
        sm.transition(LegislativeState.IDENTITY_VERIFICATION)

        # Attest only 1 of 5 producers (20% < 51% quorum)
        _attest_identity(governance_db, child_id, ["did:mock:producer-1"])

        result = sm.can_transition(LegislativeState.PROPOSAL_OPEN)
        assert not result.allowed
        assert "Quorum" in result.reason
