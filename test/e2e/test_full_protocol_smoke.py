"""E2E legislative waypoint — identity guard quorum via canonical IDENTITY_ATTESTATION.

Step 8.2 from the source plan: proves the guard reads the same enum the
Registrar writes (``IDENTITY_ATTESTATION``), not the legacy response
string used by the pre-bundle-0 protocol.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Generator

import pytest

from oasis.governance.messages import IdentityAttestation, log_message
from oasis.governance.schema import create_governance_tables, seed_constitution
from oasis.governance.state_machine import (
    GuardResult,
    LegislativeState,
    _guard_identity_to_proposal,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def gov_db(tmp_path: Path) -> Path:
    """Fresh governance DB with tables and constitution only (no clerks)."""
    db = tmp_path / "gov.db"
    create_governance_tables(db)
    seed_constitution(db)
    return db


@pytest.fixture()
def gov_conn(gov_db: Path) -> Generator[sqlite3.Connection, None, None]:
    """Yield a connection to the governance DB; auto-close."""
    conn = sqlite3.connect(str(gov_db))
    conn.execute("PRAGMA foreign_keys = ON")
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _register_producers(db_path: Path, n: int = 10) -> list[str]:
    """Register *n* active producer agents, return their DIDs."""
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA foreign_keys = ON")
    dids = []
    for i in range(1, n + 1):
        did = f"did:e2e:producer-{i:02d}"
        conn.execute(
            "INSERT INTO agent_registry "
            "(agent_did, agent_type, display_name, reputation_score, active) "
            "VALUES (?, 'producer', ?, 0.5, 1)",
            (did, f"Producer {i}"),
        )
        dids.append(did)
    conn.commit()
    conn.close()
    return dids


def _insert_session(db_path: Path, session_id: str) -> None:
    """Insert a legislative session row in IDENTITY_VERIFICATION state."""
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute(
        "INSERT INTO legislative_session (session_id, state, epoch) VALUES (?, ?, ?)",
        (session_id, LegislativeState.IDENTITY_VERIFICATION.value, 0),
    )
    conn.commit()
    conn.close()


def _insert_attestations(db_path: Path, session_id: str, dids: list[str]) -> None:
    """Log canonical IDENTITY_ATTESTATION messages for the given DIDs."""
    for did in dids:
        att = IdentityAttestation(
            session_id=session_id,
            agent_did=did,
            signature="ab" * 64,
            reputation_score=0.5,
            agent_type="producer",
        )
        log_message(db_path, session_id, att, sender_did=did)


def _delete_attestation(db_path: Path, session_id: str, did: str) -> None:
    """Remove one IDENTITY_ATTESTATION row for a DID from message_log."""
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute(
        "DELETE FROM message_log "
        "WHERE session_id = ? AND msg_type = 'IDENTITY_ATTESTATION' "
        "AND sender_did = ?",
        (session_id, did),
    )
    conn.commit()
    conn.close()


# ---------------------------------------------------------------------------
# T1 — 6/10 attestations clear 0.60 quorum
# ---------------------------------------------------------------------------


class TestGuardIdentityToProposal:
    """Direct guard evaluation for IDENTITY_VERIFICATION → PROPOSAL_OPEN."""

    def test_six_of_ten_clears_quorum(self, gov_db: Path, gov_conn: sqlite3.Connection):
        """T1: 6/10 attestations at quorum_threshold=0.60 → allowed."""
        session_id = "e2e-t1"
        dids = _register_producers(gov_db, 10)
        _insert_session(gov_db, session_id)
        _insert_attestations(gov_db, session_id, dids[:6])

        result = _guard_identity_to_proposal(session_id, gov_conn)

        assert isinstance(result, GuardResult)
        assert result.allowed is True

    def test_five_of_ten_fails_quorum(self, gov_db: Path, gov_conn: sqlite3.Connection):
        """T2: 5/10 attestations at quorum_threshold=0.60 → blocked."""
        session_id = "e2e-t2"
        dids = _register_producers(gov_db, 10)
        _insert_session(gov_db, session_id)
        _insert_attestations(gov_db, session_id, dids[:6])
        _delete_attestation(gov_db, session_id, dids[5])

        result = _guard_identity_to_proposal(session_id, gov_conn)

        assert isinstance(result, GuardResult)
        assert result.allowed is False
        assert "quorum" in result.reason.lower()

    def test_no_active_producers_blocks(
        self, gov_db: Path, gov_conn: sqlite3.Connection
    ):
        """Guard blocks when there are zero active producers."""
        session_id = "e2e-no-prod"
        _insert_session(gov_db, session_id)

        result = _guard_identity_to_proposal(session_id, gov_conn)

        assert result.allowed is False
        assert "active" in result.reason.lower() or "producer" in result.reason.lower()

    def test_reputation_floor_blocks(self, gov_db: Path, gov_conn: sqlite3.Connection):
        """Guard blocks when an attested agent is below reputation_floor."""
        session_id = "e2e-rep-floor"
        dids = _register_producers(gov_db, 5)
        # Drop one producer below the default reputation_floor (0.1)
        conn = sqlite3.connect(str(gov_db))
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute(
            "UPDATE agent_registry SET reputation_score = 0.05 WHERE agent_did = ?",
            (dids[0],),
        )
        conn.commit()
        conn.close()

        _insert_session(gov_db, session_id)
        _insert_attestations(gov_db, session_id, dids)

        result = _guard_identity_to_proposal(session_id, gov_conn)

        assert result.allowed is False
        assert "reputation floor" in result.reason.lower()

    def test_inactive_producer_not_counted(
        self, gov_db: Path, gov_conn: sqlite3.Connection
    ):
        """Attestations from inactive producers must not count toward quorum."""
        session_id = "e2e-inactive"
        dids = _register_producers(gov_db, 5)
        # De-activate producer-5
        conn = sqlite3.connect(str(gov_db))
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute(
            "UPDATE agent_registry SET active = 0 WHERE agent_did = ?",
            (dids[4],),
        )
        conn.commit()
        conn.close()

        _insert_session(gov_db, session_id)
        # Attest all 5, but only 4 are active
        _insert_attestations(gov_db, session_id, dids)

        result = _guard_identity_to_proposal(session_id, gov_conn)

        # 4/4 active producers attested = 100% ≥ 0.60
        assert result.allowed is True

    def test_inactive_producer_cannot_supply_quorum(
        self, gov_db: Path, gov_conn: sqlite3.Connection
    ):
        """Inactive producer attestations must not make a failing quorum pass."""
        session_id = "e2e-inactive-quorum"
        dids = _register_producers(gov_db, 10)
        conn = sqlite3.connect(str(gov_db))
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute(
            "UPDATE agent_registry SET active = 0 WHERE agent_did = ?",
            (dids[5],),
        )
        conn.commit()
        conn.close()

        _insert_session(gov_db, session_id)
        _insert_attestations(gov_db, session_id, dids[:6])

        result = _guard_identity_to_proposal(session_id, gov_conn)

        # Only 5 of 9 active producers attested; inactive did[5] must not count.
        assert result.allowed is False
        assert "quorum" in result.reason.lower()

    def test_quorum_edge_exact_threshold(
        self, gov_db: Path, gov_conn: sqlite3.Connection
    ):
        """Exactly 60% of 10 = 6 should clear the 0.60 threshold."""
        session_id = "e2e-edge"
        dids = _register_producers(gov_db, 10)
        _insert_session(gov_db, session_id)
        _insert_attestations(gov_db, session_id, dids[:6])

        result = _guard_identity_to_proposal(session_id, gov_conn)

        assert result.allowed is True

    def test_distinct_sender_count(self, gov_db: Path, gov_conn: sqlite3.Connection):
        """Duplicate attestations from the same DID count only once."""
        session_id = "e2e-distinct"
        dids = _register_producers(gov_db, 10)
        _insert_session(gov_db, session_id)
        # Log the same DID twice
        _insert_attestations(gov_db, session_id, dids[:3])
        _insert_attestations(gov_db, session_id, dids[:3])

        result = _guard_identity_to_proposal(session_id, gov_conn)

        # Only 3 distinct DIDs attested → 3/10 < 0.60
        assert result.allowed is False
        assert "quorum" in result.reason.lower()


# ---------------------------------------------------------------------------
# T3 — canonical enum contract (static source check)
# ---------------------------------------------------------------------------


class TestCanonicalEnumContract:
    """Ensure the e2e test suite exercises the new ``IDENTITY_ATTESTATION``
    contract and never falls back to the legacy string.
    """

    def test_no_legacy_identity_verification_response_in_source(self):
        """T3: this test file must not contain the legacy string."""
        source = Path(__file__).read_text()
        legacy = "Identity" + "Verification" + "Response"
        assert legacy not in source

    def test_canonical_enum_present_in_source(self):
        """Sanity: the canonical string is used for attestations."""
        source = Path(__file__).read_text()
        assert "IDENTITY_ATTESTATION" in source


# ---------------------------------------------------------------------------
# Bundle-2 — Impeachment E2E waypoint
# ---------------------------------------------------------------------------


def test_bundle2_impeachment_path(tmp_path: Path) -> None:
    """E2E: 5/7 supermajority impeaches Adj0; full stake slash; ban in both registries.

    Uses live ``eth_account.Account.create()`` keypairs — EIP-712 sign/verify
    are NOT stubbed.  The test is *red* until ``oasis.adjudication.impeachment``
    (Feature 6) is merged; that is the expected Bundle-2 e2e waypoint contract.
    """
    import sqlite3

    from eth_account import Account

    from oasis.adjudication.impeachment import submit_motion, tally_motion
    from oasis.adjudication.schema import create_adjudication_tables
    from oasis.crypto.eip712 import sign
    from oasis.crypto.typed_data import DOMAIN
    from oasis.governance.schema import create_governance_tables, seed_constitution

    gov_db = tmp_path / "gov.db"
    adj_db = tmp_path / "adj.db"

    create_governance_tables(gov_db)
    seed_constitution(gov_db)
    create_adjudication_tables(adj_db)

    # Mint 7 real adjudicator keypairs
    adjudicators = []
    for i in range(7):
        acct = Account.create()
        did = f"did:key:zAdj{i}"
        adjudicators.append({"did": did, "acct": acct})

    conn_adj = sqlite3.connect(str(adj_db))
    conn_adj.execute("PRAGMA foreign_keys = ON")
    conn_adj.row_factory = sqlite3.Row

    conn_gov = sqlite3.connect(str(gov_db))
    conn_gov.execute("PRAGMA foreign_keys = ON")
    conn_gov.row_factory = sqlite3.Row

    try:
        # T1 — seed 7 rows in each of the three tables
        for adj in adjudicators:
            did = adj["did"]
            acct = adj["acct"]

            conn_adj.execute(
                "INSERT INTO adjudicator_registry (adjudicator_did, eth_address, stake_amount) "
                "VALUES (?, ?, ?)",
                (did, acct.address, 5000.0),
            )
            conn_adj.execute(
                "INSERT INTO agent_balance (agent_did, total_balance, locked_stake, available_balance) "
                "VALUES (?, ?, ?, ?)",
                (did, 5000.0, 5000.0, 0.0),
            )
            # agent_registry in gov DB — include NOT NULL columns from prior bundles
            conn_gov.execute(
                "INSERT INTO agent_registry (agent_did, agent_type, display_name, reputation_score, active) "
                "VALUES (?, ?, ?, ?, ?)",
                (did, "producer", f"Adjudicator {did}", 0.5, 1),
            )

        conn_adj.commit()
        conn_gov.commit()

        assert (
            conn_adj.execute("SELECT COUNT(*) FROM adjudicator_registry").fetchone()[0]
            == 7
        )
        assert conn_adj.execute("SELECT COUNT(*) FROM agent_balance").fetchone()[0] == 7
        assert (
            conn_gov.execute("SELECT COUNT(*) FROM agent_registry").fetchone()[0] == 7
        )

        target_did = "did:key:zAdj0"
        evidence_cid = "ipfs://smoke"
        motion_id = "smoke-motion-1"

        # 5 adjudicators (Adj1–Adj5) sign the impeachment motion
        signatures = []
        for adj in adjudicators[1:6]:
            message = {
                "target_did": target_did,
                "evidence_cid": evidence_cid,
                "motion_id": motion_id,
            }
            sig = sign(adj["acct"].key, DOMAIN, "Impeachment", message)
            signatures.append({"signer": adj["acct"].address, "signature": sig.hex()})

        # T2 — submit then tally
        submit_motion(
            motion_id=motion_id,
            target_did=target_did,
            evidence_cid=evidence_cid,
            signatures=signatures,
            adj_db_path=str(adj_db),
            gov_db_path=str(gov_db),
            agents_in_mission=(),
        )
        verdict = tally_motion(
            motion_id=motion_id,
            adj_db_path=str(adj_db),
            gov_db_path=str(gov_db),
            agents_in_mission=(),
        )

        assert verdict.status == "accepted"
        assert verdict.slashed_amount == 5000.0

        # T3 — ban applied in both registries
        row_adj = conn_adj.execute(
            "SELECT is_banned FROM adjudicator_registry WHERE adjudicator_did = ?",
            (target_did,),
        ).fetchone()
        assert row_adj is not None
        assert row_adj["is_banned"] == 1

        row_gov = conn_gov.execute(
            "SELECT banned FROM agent_registry WHERE agent_did = ?",
            (target_did,),
        ).fetchone()
        assert row_gov is not None
        assert row_gov["banned"] == 1
    finally:
        conn_adj.close()
        conn_gov.close()


# ---------------------------------------------------------------------------
# Bundle-3 — Anchoring and Reconciliation E2E waypoint
# ---------------------------------------------------------------------------


def test_bundle3_anchoring_and_reconciliation(tmp_path):
    """End-to-end: emit 100 events into a mission, anchor them, run
    reconciliation. Then tamper one event and re-run; expect DIVERGED."""
    from oasis.adjudication.anchor_publisher import publish_anchor
    from oasis.adjudication.reconciliation import reconcile_mission
    from oasis.observatory.schema import create_observatory_tables
    import sqlite3
    import json

    obs_db = tmp_path / "obs.db"
    create_observatory_tables(str(obs_db))

    # Emit 100 mission events
    conn = sqlite3.connect(str(obs_db))
    for i in range(100):
        conn.execute(
            "INSERT INTO event_log "
            "(event_id, event_type, timestamp, payload, sequence_number, mission_id) "
            "VALUES (?, 'TASK', ?, ?, ?, 'mission-smoke')",
            (f"e{i}", float(i), json.dumps({"i": i}, sort_keys=True), i + 1),
        )
    conn.commit()
    conn.close()

    anchor = publish_anchor(
        db_path=str(obs_db), batch_max_size=1000, mission_id="mission-smoke"
    )
    assert anchor["event_count"] == 100

    result = reconcile_mission(mission_id="mission-smoke", db_path=str(obs_db))
    assert result.status == "PASS"

    # Tamper
    conn = sqlite3.connect(str(obs_db))
    conn.execute(
        "UPDATE event_log SET payload = '{\"tampered\": 1}' WHERE event_id = 'e42'"
    )
    conn.commit()
    conn.close()

    result2 = reconcile_mission(mission_id="mission-smoke", db_path=str(obs_db))
    assert result2.status == "DIVERGED"


# ---------------------------------------------------------------------------
# Bundle-4 — Execution State Machine E2E waypoint
# ---------------------------------------------------------------------------


def test_bundle4_full_state_machine_traversal(tmp_path):
    """Drive a single task from WAITING through every state to
    COMPLETED via PENDING_VERIFICATION. Assert task_state_transition
    audit row exists for each step."""
    from oasis.execution.schema import create_execution_tables
    from oasis.execution.state_machine import (
        ExecutionNodeState,
        transition,
    )
    import sqlite3

    db = tmp_path / "exec.db"
    create_execution_tables(str(db))

    # Seed task in WAITING
    conn = sqlite3.connect(str(db))
    conn.execute(
        "INSERT INTO task_assignment "
        "(task_id, session_id, node_id, agent_did, state) "
        "VALUES ('smoke-t1', 's1', 'n1', 'a1', 'WAITING')"
    )
    conn.commit()
    conn.close()

    # WAITING → ELIGIBLE (no predecessors)
    transition(
        task_id="smoke-t1",
        to_state=ExecutionNodeState.ELIGIBLE,
        reason="root node",
        db_path=str(db),
    )

    # ELIGIBLE → EXECUTING
    transition(
        task_id="smoke-t1",
        to_state=ExecutionNodeState.EXECUTING,
        reason="routeTask",
        db_path=str(db),
    )

    # EXECUTING → PENDING_VERIFICATION (Tier 1)
    transition(
        task_id="smoke-t1",
        to_state=ExecutionNodeState.PENDING_VERIFICATION,
        reason="Tier 1 output submitted",
        db_path=str(db),
    )

    # PENDING_VERIFICATION → COMPLETED
    transition(
        task_id="smoke-t1",
        to_state=ExecutionNodeState.COMPLETED,
        reason="PoP passed",
        db_path=str(db),
    )

    # Verify audit trail
    conn = sqlite3.connect(str(db))
    rows = conn.execute(
        "SELECT from_state, to_state FROM task_state_transition "
        "WHERE task_id = 'smoke-t1' ORDER BY transitioned_at ASC"
    ).fetchall()
    conn.close()
    assert rows == [
        ("WAITING", "ELIGIBLE"),
        ("ELIGIBLE", "EXECUTING"),
        ("EXECUTING", "PENDING_VERIFICATION"),
        ("PENDING_VERIFICATION", "COMPLETED"),
    ]


def test_bundle4_illegal_skip_rejected(tmp_path):
    """Try to skip from EXECUTING straight to COMPLETED. Must be rejected."""
    from oasis.execution.schema import create_execution_tables
    from oasis.execution.state_machine import (
        ExecutionNodeState,
        can_transition,
    )
    import sqlite3

    db = tmp_path / "exec.db"
    create_execution_tables(str(db))
    conn = sqlite3.connect(str(db))
    conn.execute(
        "INSERT INTO task_assignment "
        "(task_id, session_id, node_id, agent_did, state) "
        "VALUES ('t-skip', 's1', 'n1', 'a1', 'EXECUTING')"
    )
    conn.commit()
    conn.close()

    result = can_transition(
        task_id="t-skip",
        from_state=ExecutionNodeState.EXECUTING,
        to_state=ExecutionNodeState.COMPLETED,
        db_path=str(db),
    )
    assert result.allowed is False, "SP-2 violation must be rejected"


def test_bundle4_audit_trail_timestamps(tmp_path):
    """Every transition writes a row with a non-null timestamp."""
    from oasis.execution.schema import create_execution_tables
    from oasis.execution.state_machine import (
        ExecutionNodeState,
        transition,
    )
    import sqlite3

    db = tmp_path / "exec.db"
    create_execution_tables(str(db))
    conn = sqlite3.connect(str(db))
    conn.execute(
        "INSERT INTO task_assignment "
        "(task_id, session_id, node_id, agent_did, state) "
        "VALUES ('t-time', 's1', 'n1', 'a1', 'WAITING')"
    )
    conn.commit()
    conn.close()

    transition(
        task_id="t-time",
        to_state=ExecutionNodeState.ELIGIBLE,
        reason="root node",
        db_path=str(db),
    )
    transition(
        task_id="t-time",
        to_state=ExecutionNodeState.EXECUTING,
        reason="routeTask",
        db_path=str(db),
    )

    conn = sqlite3.connect(str(db))
    rows = conn.execute(
        "SELECT transitioned_at FROM task_state_transition "
        "WHERE task_id = 't-time' ORDER BY transitioned_at ASC"
    ).fetchall()
    conn.close()
    assert len(rows) == 2
    for row in rows:
        assert row[0] is not None, "transitioned_at must not be NULL"


def test_bundle4_task_assignment_state_updated(tmp_path):
    """transition() must update the state column in task_assignment."""
    from oasis.execution.schema import create_execution_tables
    from oasis.execution.state_machine import (
        ExecutionNodeState,
        transition,
    )
    import sqlite3

    db = tmp_path / "exec.db"
    create_execution_tables(str(db))
    conn = sqlite3.connect(str(db))
    conn.execute(
        "INSERT INTO task_assignment "
        "(task_id, session_id, node_id, agent_did, state) "
        "VALUES ('t-update', 's1', 'n1', 'a1', 'WAITING')"
    )
    conn.commit()
    conn.close()

    transition(
        task_id="t-update",
        to_state=ExecutionNodeState.ELIGIBLE,
        reason="root node",
        db_path=str(db),
    )

    conn = sqlite3.connect(str(db))
    row = conn.execute(
        "SELECT state FROM task_assignment WHERE task_id = 't-update'"
    ).fetchone()
    conn.close()
    assert row[0] == "ELIGIBLE"


def test_bundle4_state_check_constraint_enforced(tmp_path):
    """Invalid state values must be rejected by the CHECK constraint."""
    from oasis.execution.schema import create_execution_tables
    import sqlite3

    db = tmp_path / "exec.db"
    create_execution_tables(str(db))
    conn = sqlite3.connect(str(db))
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO task_assignment "
            "(task_id, session_id, node_id, agent_did, state) "
            "VALUES ('t-bad', 's1', 'n1', 'a1', 'INVALID_STATE')"
        )
    conn.close()


def test_bundle4_legacy_status_synced_during_traversal(tmp_path):
    """Legacy status column stays in sync with state through the E2E traversal."""
    from oasis.execution.schema import create_execution_tables
    from oasis.execution.state_machine import (
        ExecutionNodeState,
        transition,
        STATE_TO_LEGACY_STATUS,
    )
    import sqlite3

    db = tmp_path / "exec.db"
    create_execution_tables(str(db))
    conn = sqlite3.connect(str(db))
    conn.execute(
        "INSERT INTO task_assignment "
        "(task_id, session_id, node_id, agent_did, state) "
        "VALUES ('t-legacy', 's1', 'n1', 'a1', 'WAITING')"
    )
    conn.commit()
    conn.close()

    for state in (
        ExecutionNodeState.ELIGIBLE,
        ExecutionNodeState.EXECUTING,
        ExecutionNodeState.PENDING_VERIFICATION,
        ExecutionNodeState.COMPLETED,
    ):
        transition(
            task_id="t-legacy",
            to_state=state,
            reason="test",
            db_path=str(db),
        )
        conn = sqlite3.connect(str(db))
        row = conn.execute(
            "SELECT state, status FROM task_assignment WHERE task_id = 't-legacy'"
        ).fetchone()
        conn.close()
        assert row[0] == state.value
        assert row[1] == STATE_TO_LEGACY_STATUS.get(state, "")


def test_bundle4_pending_review_to_completed_allowed(tmp_path):
    """Tier 3 tasks traverse PENDING_REVIEW before COMPLETED."""
    from oasis.execution.schema import create_execution_tables
    from oasis.execution.state_machine import (
        ExecutionNodeState,
        can_transition,
        transition,
    )
    import sqlite3

    db = tmp_path / "exec.db"
    create_execution_tables(str(db))
    conn = sqlite3.connect(str(db))
    conn.execute(
        "INSERT INTO task_assignment "
        "(task_id, session_id, node_id, agent_did, state) "
        "VALUES ('t-review', 's1', 'n1', 'a1', 'EXECUTING')"
    )
    conn.commit()
    conn.close()

    # EXECUTING → PENDING_REVIEW is legal
    result = can_transition(
        task_id="t-review",
        from_state=ExecutionNodeState.EXECUTING,
        to_state=ExecutionNodeState.PENDING_REVIEW,
        db_path=str(db),
    )
    assert result.allowed is True

    transition(
        task_id="t-review",
        to_state=ExecutionNodeState.PENDING_REVIEW,
        reason="Tier 3 output submitted",
        db_path=str(db),
    )

    # PENDING_REVIEW → COMPLETED is legal
    result2 = can_transition(
        task_id="t-review",
        from_state=ExecutionNodeState.PENDING_REVIEW,
        to_state=ExecutionNodeState.COMPLETED,
        db_path=str(db),
    )
    assert result2.allowed is True

    transition(
        task_id="t-review",
        to_state=ExecutionNodeState.COMPLETED,
        reason="PoP passed",
        db_path=str(db),
    )

    conn = sqlite3.connect(str(db))
    rows = conn.execute(
        "SELECT from_state, to_state FROM task_state_transition "
        "WHERE task_id = 't-review' ORDER BY transitioned_at ASC"
    ).fetchall()
    conn.close()
    assert rows == [
        ("EXECUTING", "PENDING_REVIEW"),
        ("PENDING_REVIEW", "COMPLETED"),
    ]


# ---------------------------------------------------------------------------
# Bundle 5 — Legislative Dynamics waypoints
# ---------------------------------------------------------------------------


def test_bundle5_adaptive_refinement_chain(tmp_path: Path) -> None:
    """Adaptive refinement: 3 successive task_failed events fire, 4th is
    blocked by the iteration budget."""
    from oasis.governance.adaptive_refinement import (
        get_iteration_budget,
        on_task_failed,
    )
    from oasis.governance.schema import create_governance_tables, seed_constitution

    db = tmp_path / "g.db"
    create_governance_tables(str(db))
    seed_constitution(str(db))

    for i in range(3):
        result = on_task_failed(task_id="t-smoke", gov_db_path=str(db))
        assert result is not None, f"refinement {i + 1} should fire"

    # 4th must be blocked.
    assert on_task_failed(task_id="t-smoke", gov_db_path=str(db)) is None
    assert get_iteration_budget(parent_task_id="t-smoke", db_path=str(db)) == 3


def test_bundle5_petition_to_session(tmp_path: Path) -> None:
    """Petition flow: 10 producers, 2 sign → threshold met, session fires."""
    import sqlite3

    from oasis.governance.schema import create_governance_tables, seed_constitution
    from oasis.governance.scheduler.petition_trigger import (
        accumulate_signature,
        check_threshold,
        fire_petition,
    )

    db = tmp_path / "g.db"
    create_governance_tables(str(db))
    seed_constitution(str(db))

    conn = sqlite3.connect(str(db))
    for i in range(10):
        conn.execute(
            "INSERT INTO agent_registry "
            "(agent_did, agent_type, capability_tier, display_name, active) "
            "VALUES (?, 'producer', 't1', ?, 1)",
            (f"did:key:zProd{i}", f"prod-{i}"),
        )
    conn.execute(
        "INSERT INTO petition "
        "(petition_id, title, rationale, proposed_mission) "
        "VALUES ('pet-e2e', 't', 'r', 'study X')"
    )
    conn.commit()
    conn.close()

    for i in range(2):
        accumulate_signature(
            petition_id="pet-e2e",
            signer_did=f"did:key:zProd{i}",
            signature_hex="00" * 64,
            db_path=str(db),
        )

    assert check_threshold(petition_id="pet-e2e", db_path=str(db)) is True

    session_id = fire_petition(petition_id="pet-e2e", db_path=str(db))
    conn = sqlite3.connect(str(db))
    row = conn.execute(
        "SELECT trigger, state FROM legislative_session WHERE session_id = ?",
        (session_id,),
    ).fetchone()
    conn.close()
    assert row == ("petition", "SESSION_INIT")


def test_bundle5_milestone_trigger_end_to_end(tmp_path: Path) -> None:
    """Milestone trigger: 20 settled tasks → milestone fires from scheduler."""
    import sqlite3

    from oasis.adjudication.schema import create_adjudication_tables
    from oasis.adjudication.scheduler import start_scheduler, stop_scheduler
    from oasis.execution.schema import create_execution_tables
    from oasis.governance.schema import create_governance_tables, seed_constitution

    gov_db = tmp_path / "gov.db"
    adj_db = tmp_path / "adj.db"
    exec_db = tmp_path / "exec.db"
    create_governance_tables(str(gov_db))
    seed_constitution(str(gov_db))
    create_adjudication_tables(str(adj_db))
    create_execution_tables(str(exec_db))

    conn = sqlite3.connect(str(exec_db))
    for i in range(20):
        conn.execute(
            "INSERT INTO settlement "
            "(settlement_id, task_id, agent_did, base_reward, "
            "reputation_multiplier, final_reward, protocol_fee, "
            "insurance_fee) "
            "VALUES (?, ?, 'did:key:zA', 10.0, 1.0, 10.0, 0.5, 0.5)",
            (f"settle-{i}", f"task-{i}"),
        )
    conn.commit()
    conn.close()

    try:
        sched = start_scheduler(
            adj_db_path=str(adj_db),
            gov_db_path=str(gov_db),
            exec_db_path=str(exec_db),
        )
        sched.get_job("milestone_trigger").func()
        conn = sqlite3.connect(str(gov_db))
        rows = conn.execute(
            "SELECT trigger FROM legislative_session WHERE trigger = 'milestone'"
        ).fetchall()
        conn.close()
        assert len(rows) == 1
    finally:
        stop_scheduler()
