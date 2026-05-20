"""T2–T4, T20–T21 — log_message crypto behaviour (Feature 6, Feature 11).

Tests the new ``cosigner_did`` kwarg, unsigned-MSG1 handling, payload/payload_json
split, and the synthetic MSG7 cosig row.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from oasis.crypto import ed25519
from oasis.crypto.did import did_from_pubkey
from oasis.governance.messages import (
    IdentityAttestation,
    IdentityVerificationRequest,
    LegislativeApproval,
    MessageType,
    canonical_signed_bytes,
    get_session_messages,
    log_message,
)
from oasis.governance.schema import create_governance_tables


def _connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA foreign_keys = ON")
    conn.row_factory = sqlite3.Row
    return conn


def _register_agent(conn: sqlite3.Connection, agent_did: str, public_key: bytes) -> None:
    conn.execute(
        "INSERT OR IGNORE INTO agent_registry "
        "(agent_did, agent_type, display_name, human_principal, public_key) "
        "VALUES (?, ?, ?, ?, ?)",
        (agent_did, "producer", "Test Agent", "test@example.com", public_key.hex()),
    )
    conn.commit()


def _make_signed_attestation(
    session_id: str, agent_did: str, private_key: bytes
) -> IdentityAttestation:
    msg = IdentityAttestation(
        session_id=session_id,
        agent_did=agent_did,
        signature="ab" * 64,
        reputation_score=0.5,
        agent_type="producer",
    )
    canonical = canonical_signed_bytes(msg)
    msg.signature = ed25519.sign(private_key, canonical).hex()
    return msg


def _insert_session(db_path: Path, session_id: str) -> None:
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute(
        "INSERT INTO legislative_session (session_id, state, epoch) VALUES (?, ?, ?)",
        (session_id, "SESSION_INIT", 0),
    )
    conn.commit()
    conn.close()


# ---------------------------------------------------------------------------
# T2 — log_message stores canonical hex in payload
# ---------------------------------------------------------------------------


def test_t2_log_message_stores_canonical_hex_payload(db_path: Path):
    """Signed MSG2: payload == canonical hex, signature == msg.signature,
    payload_json == model_dump_json()."""
    create_governance_tables(db_path)
    _insert_session(db_path, "s2")
    priv, pub = ed25519.generate_keypair()
    agent_did = did_from_pubkey(pub)
    conn = _connect(db_path)
    _register_agent(conn, agent_did, pub)
    conn.close()

    msg = _make_signed_attestation("s2", agent_did, priv)
    expected_payload = canonical_signed_bytes(msg).hex()

    log_message(db_path, "s2", msg, sender_did=agent_did)

    conn = _connect(db_path)
    row = conn.execute(
        "SELECT payload, signature, payload_json FROM message_log WHERE session_id = ?",
        ("s2",),
    ).fetchone()
    conn.close()

    assert row["payload"] == expected_payload
    assert row["signature"] == msg.signature
    assert row["payload_json"] == msg.model_dump_json()


# ---------------------------------------------------------------------------
# T3 — log_message handles unsigned MSG1
# ---------------------------------------------------------------------------


def test_t3_log_message_unsigned_msg1(db_path: Path):
    """MSG1 (no signature field) → payload empty string, signature NULL,
    payload_json set."""
    create_governance_tables(db_path)
    _insert_session(db_path, "s3")

    msg = IdentityVerificationRequest(session_id="s3", min_reputation=0.1)
    log_message(db_path, "s3", msg, sender_did="system")

    conn = _connect(db_path)
    row = conn.execute(
        "SELECT payload, signature, payload_json FROM message_log WHERE session_id = ?",
        ("s3",),
    ).fetchone()
    conn.close()

    assert row["payload"] == ""
    assert row["signature"] is None
    assert row["payload_json"] == msg.model_dump_json()


# ---------------------------------------------------------------------------
# T4 — round-trip via get_session_messages
# ---------------------------------------------------------------------------


def test_t4_round_trip_get_session_messages(db_path: Path):
    """Log signed MSG2 + unsigned MSG1; get_session_messages returns hex payload
    for signed row and JSON via payload_json."""
    create_governance_tables(db_path)
    _insert_session(db_path, "s4")
    priv, pub = ed25519.generate_keypair()
    agent_did = did_from_pubkey(pub)
    conn = _connect(db_path)
    _register_agent(conn, agent_did, pub)
    conn.close()

    msg2 = _make_signed_attestation("s4", agent_did, priv)
    msg1 = IdentityVerificationRequest(session_id="s4", min_reputation=0.1)

    log_message(db_path, "s4", msg2, sender_did=agent_did)
    log_message(db_path, "s4", msg1, sender_did="system")

    messages = get_session_messages(db_path, "s4")
    assert len(messages) == 2

    # MSG2 row
    msg2_row = messages[0]
    assert msg2_row["msg_type"] == MessageType.IDENTITY_ATTESTATION.value
    # payload is the hex string (not parsed JSON)
    assert isinstance(msg2_row["payload"], str)
    assert msg2_row["payload"] == canonical_signed_bytes(msg2).hex()
    assert msg2_row["signature"] == msg2.signature
    # JSON fields accessible via payload_json
    assert msg2_row["payload_json"]["signature"] == msg2.signature

    # MSG1 row
    msg1_row = messages[1]
    assert msg1_row["msg_type"] == MessageType.IDENTITY_VERIFICATION_REQUEST.value


# ---------------------------------------------------------------------------
# T20 — MSG7 cosig persistence writes both rows
# ---------------------------------------------------------------------------


def test_t20_msg7_cosig_persistence_writes_both_rows(db_path: Path):
    """log_message with cosigner_did writes primary + cosig rows."""
    create_governance_tables(db_path)
    _insert_session(db_path, "s20")

    spk_priv, spk_pub = ed25519.generate_keypair()
    reg_priv, reg_pub = ed25519.generate_keypair()
    speaker_did = did_from_pubkey(spk_pub)
    regulator_did = did_from_pubkey(reg_pub)

    conn = _connect(db_path)
    _register_agent(conn, speaker_did, spk_pub)
    _register_agent(conn, regulator_did, reg_pub)
    conn.close()

    msg7 = LegislativeApproval(
        session_id="s20",
        spec_id="spec-abc",
        speaker_signature="ab" * 64,
        regulator_signature="ab" * 64,
    )
    canonical = canonical_signed_bytes(msg7)
    msg7.speaker_signature = ed25519.sign(spk_priv, canonical).hex()
    msg7.regulator_signature = ed25519.sign(reg_priv, canonical).hex()

    log_message(
        db_path,
        session_id="s20",
        msg=msg7,
        sender_did=speaker_did,
        cosigner_did=regulator_did,
    )

    conn = _connect(db_path)
    rows = conn.execute(
        "SELECT msg_type, sender_did, payload, signature, payload_json "
        "FROM message_log WHERE session_id = ? ORDER BY rowid",
        ("s20",),
    ).fetchall()
    conn.close()

    assert len(rows) == 2

    # Row 1: primary LEGISLATIVE_APPROVAL
    r1 = rows[0]
    assert r1["msg_type"] == MessageType.LEGISLATIVE_APPROVAL.value
    assert r1["sender_did"] == speaker_did
    assert r1["payload"] == canonical.hex()
    assert r1["signature"] == msg7.speaker_signature
    assert r1["payload_json"] == msg7.model_dump_json()

    # Row 2: synthetic REGULATOR_COSIG
    r2 = rows[1]
    assert r2["msg_type"] == MessageType.LEGISLATIVE_APPROVAL_REGULATOR_COSIG.value
    assert r2["sender_did"] == regulator_did
    assert r2["payload"] == canonical.hex()
    assert r2["signature"] == msg7.regulator_signature
    assert r2["payload_json"] == msg7.model_dump_json()


# ---------------------------------------------------------------------------
# T21 — MSG7 without cosigner_did writes only one row
# ---------------------------------------------------------------------------


def test_t21_msg7_without_cosigner_did_writes_one_row(db_path: Path):
    """log_message without cosigner_did kwarg writes exactly one row."""
    create_governance_tables(db_path)
    _insert_session(db_path, "s21")

    spk_priv, spk_pub = ed25519.generate_keypair()
    speaker_did = did_from_pubkey(spk_pub)
    conn = _connect(db_path)
    _register_agent(conn, speaker_did, spk_pub)
    conn.close()

    msg7 = LegislativeApproval(
        session_id="s21",
        spec_id="spec-abc",
        speaker_signature="ab" * 64,
        regulator_signature="ab" * 64,
    )
    canonical = canonical_signed_bytes(msg7)
    msg7.speaker_signature = ed25519.sign(spk_priv, canonical).hex()
    # regulator_signature stays placeholder — we don't pass cosigner_did

    log_message(db_path, session_id="s21", msg=msg7, sender_did=speaker_did)

    conn = _connect(db_path)
    rows = conn.execute(
        "SELECT msg_type FROM message_log WHERE session_id = ?",
        ("s21",),
    ).fetchall()
    conn.close()

    assert len(rows) == 1
    assert rows[0]["msg_type"] == MessageType.LEGISLATIVE_APPROVAL.value


# ---------------------------------------------------------------------------
# Enum existence — LEGISLATIVE_APPROVAL_REGULATOR_COSIG
# ---------------------------------------------------------------------------


def test_t20_msg7_cosig_enum_exists():
    """MessageType.LEGISLATIVE_APPROVAL_REGULATOR_COSIG is a valid enum member."""
    assert hasattr(MessageType, "LEGISLATIVE_APPROVAL_REGULATOR_COSIG")
    assert (
        MessageType.LEGISLATIVE_APPROVAL_REGULATOR_COSIG.value
        == "LEGISLATIVE_APPROVAL_REGULATOR_COSIG"
    )
