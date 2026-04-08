"""Tests: message logging to DB, filtering by type, chronological order (3 tests)."""
from __future__ import annotations

from pathlib import Path

from oasis.governance.messages import (
    DAGProposal,
    IdentityVerificationRequest,
    MessageType,
    TaskBid,
    get_session_messages,
    log_message,
)


def test_message_logged_to_db(governance_db: Path):
    """A logged message appears in the message_log table."""
    session_id = "sess-log-001"
    # Create session row for FK
    import sqlite3
    conn = sqlite3.connect(str(governance_db))
    conn.execute(
        "INSERT INTO legislative_session (session_id, state, epoch) VALUES (?, ?, ?)",
        (session_id, "SESSION_INIT", 0),
    )
    conn.commit()
    conn.close()

    msg = IdentityVerificationRequest(
        session_id=session_id,
        min_reputation=0.2,
    )
    log_id = log_message(governance_db, session_id, msg, sender_did="did:oasis:clerk-registrar")
    assert log_id is not None
    assert log_id > 0

    messages = get_session_messages(governance_db, session_id)
    assert len(messages) == 1
    assert messages[0]["msg_type"] == MessageType.IDENTITY_VERIFICATION_REQUEST.value


def test_messages_filterable_by_type(governance_db: Path):
    """get_session_messages returns only messages of the requested type."""
    session_id = "sess-log-002"
    import sqlite3
    conn = sqlite3.connect(str(governance_db))
    conn.execute(
        "INSERT INTO legislative_session (session_id, state, epoch) VALUES (?, ?, ?)",
        (session_id, "SESSION_INIT", 0),
    )
    conn.commit()
    conn.close()

    msg1 = IdentityVerificationRequest(session_id=session_id, min_reputation=0.1)
    msg2 = TaskBid(
        session_id=session_id,
        task_node_id="node-1",
        bidder_did="did:mock:producer-1",
        service_id="svc-1",
        proposed_code_hash="hash-abc",
        stake_amount=5.0,
        estimated_latency_ms=3000,
        pop_tier_acceptance=1,
    )

    log_message(governance_db, session_id, msg1, sender_did="did:oasis:clerk-registrar")
    log_message(governance_db, session_id, msg2, sender_did="did:mock:producer-1")

    all_msgs = get_session_messages(governance_db, session_id)
    assert len(all_msgs) == 2

    bids_only = get_session_messages(governance_db, session_id, msg_type=MessageType.TASK_BID)
    assert len(bids_only) == 1
    assert bids_only[0]["msg_type"] == MessageType.TASK_BID.value


def test_messages_chronological_order(governance_db: Path):
    """Messages are returned in insertion (chronological) order."""
    session_id = "sess-log-003"
    import sqlite3
    conn = sqlite3.connect(str(governance_db))
    conn.execute(
        "INSERT INTO legislative_session (session_id, state, epoch) VALUES (?, ?, ?)",
        (session_id, "SESSION_INIT", 0),
    )
    conn.commit()
    conn.close()

    msg1 = IdentityVerificationRequest(session_id=session_id, min_reputation=0.1)
    dag_spec = {"nodes": [{"id": "n1", "label": "A"}], "edges": []}
    msg2 = DAGProposal(
        session_id=session_id,
        proposer_did="did:mock:producer-1",
        dag_spec=dag_spec,
        rationale="test",
        token_budget_total=100.0,
        deadline_ms=60000,
    )
    msg3 = TaskBid(
        session_id=session_id,
        task_node_id="node-1",
        bidder_did="did:mock:producer-2",
        service_id="svc-1",
        proposed_code_hash="hash-xyz",
        stake_amount=8.0,
        estimated_latency_ms=4000,
        pop_tier_acceptance=2,
    )

    log_message(governance_db, session_id, msg1, sender_did="registrar")
    log_message(governance_db, session_id, msg2, sender_did="producer-1")
    log_message(governance_db, session_id, msg3, sender_did="producer-2")

    messages = get_session_messages(governance_db, session_id)
    assert len(messages) == 3
    # log_id is monotonically increasing — confirms chronological order
    assert messages[0]["log_id"] < messages[1]["log_id"] < messages[2]["log_id"]
    assert messages[0]["msg_type"] == MessageType.IDENTITY_VERIFICATION_REQUEST.value
    assert messages[1]["msg_type"] == MessageType.DAG_PROPOSAL.value
    assert messages[2]["msg_type"] == MessageType.TASK_BID.value
