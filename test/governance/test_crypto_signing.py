"""T1, T8–T13 — verify_message_signature helper (Feature 8).

These tests import ``verify_message_signature`` from the *not-yet-implemented*
module ``oasis.crypto._signing``.  They will fail at import time during the
Red phase, then pass once the helper is written.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from oasis.crypto import ed25519
from oasis.crypto.did import did_from_pubkey
from oasis.governance.messages import (
    IdentityAttestation,
    LegislativeApproval,
    RegulatoryDecision,
    canonical_signed_bytes,
)
from oasis.governance.schema import create_governance_tables


@pytest.fixture(scope="module")
def verify_message_signature():
    """Lazy import so collection succeeds during Red phase."""
    from oasis.crypto._signing import verify_message_signature as fn

    return fn


def _connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA foreign_keys = ON")
    conn.row_factory = sqlite3.Row
    return conn


def _register_agent(
    conn: sqlite3.Connection, agent_did: str, public_key: bytes
) -> None:
    conn.execute(
        "INSERT OR IGNORE INTO agent_registry "
        "(agent_did, agent_type, display_name, human_principal, public_key) "
        "VALUES (?, ?, ?, ?, ?)",
        (agent_did, "producer", "Test Agent", "test@example.com", public_key.hex()),
    )
    conn.commit()


def _make_signed_attestation(
    session_id: str,
    agent_did: str,
    reputation_score: float,
    private_key: bytes,
) -> IdentityAttestation:
    """Build and sign an IdentityAttestation (MSG2)."""
    msg = IdentityAttestation(
        session_id=session_id,
        agent_did=agent_did,
        signature="ab" * 64,  # placeholder
        reputation_score=reputation_score,
        agent_type="producer",
    )
    canonical = canonical_signed_bytes(msg)
    sig = ed25519.sign(private_key, canonical)
    msg.signature = sig.hex()
    return msg


# ---------------------------------------------------------------------------
# T1 — helper happy path
# ---------------------------------------------------------------------------


def test_t1_verify_helper_happy_path(
    db_path: Path, ed25519_keypair: tuple[bytes, bytes], verify_message_signature
):
    """Registered agent + valid signature → (True, [])."""
    priv, pub = ed25519_keypair
    agent_did = did_from_pubkey(pub)
    create_governance_tables(db_path)
    conn = _connect(db_path)
    _register_agent(conn, agent_did, pub)

    msg = _make_signed_attestation("s1", agent_did, 0.5, priv)
    ok, errs = verify_message_signature(msg=msg, sender_did=agent_did, conn=conn)
    assert ok is True
    assert errs == []
    conn.close()


# ---------------------------------------------------------------------------
# T8 — unregistered sender
# ---------------------------------------------------------------------------


def test_t8_verify_helper_unregistered_sender(db_path: Path, verify_message_signature):
    """No row in agent_registry → (False, [err]) mentioning 'public_key'."""
    create_governance_tables(db_path)
    conn = _connect(db_path)
    priv, pub = ed25519.generate_keypair()
    agent_did = did_from_pubkey(pub)

    msg = _make_signed_attestation("s1", agent_did, 0.5, priv)
    ok, errs = verify_message_signature(
        msg=msg, sender_did="did:key:zRandomNotRegistered", conn=conn
    )
    assert ok is False
    assert any("public_key" in e.lower() for e in errs)
    conn.close()


# ---------------------------------------------------------------------------
# T9 — bad signature (wrong key)
# ---------------------------------------------------------------------------


def test_t9_verify_helper_bad_signature(
    db_path: Path, ed25519_keypair: tuple[bytes, bytes], verify_message_signature
):
    """Sig from a different key → (False, [err]) mentioning 'verification failed'."""
    priv, pub = ed25519_keypair
    agent_did = did_from_pubkey(pub)
    create_governance_tables(db_path)
    conn = _connect(db_path)
    _register_agent(conn, agent_did, pub)

    # Sign with the agent's own key but then tamper the signature
    msg = _make_signed_attestation("s1", agent_did, 0.5, priv)
    wrong_priv, _ = ed25519.generate_keypair()
    bad_sig = ed25519.sign(wrong_priv, canonical_signed_bytes(msg))
    msg.signature = bad_sig.hex()

    ok, errs = verify_message_signature(msg=msg, sender_did=agent_did, conn=conn)
    assert ok is False
    assert any("verification failed" in e.lower() for e in errs)
    conn.close()


# ---------------------------------------------------------------------------
# T10 — canonical re-derivation catches field tampering
# ---------------------------------------------------------------------------


def test_t10_verify_helper_detects_field_tampering(
    db_path: Path, ed25519_keypair: tuple[bytes, bytes], verify_message_signature
):
    """Sign correct bytes, tamper a field, helper rejects."""
    priv, pub = ed25519_keypair
    agent_did = did_from_pubkey(pub)
    create_governance_tables(db_path)
    conn = _connect(db_path)
    _register_agent(conn, agent_did, pub)

    msg = _make_signed_attestation("s1", agent_did, 0.5, priv)
    # Tamper reputation_score after signing
    msg.reputation_score = 0.99

    ok, errs = verify_message_signature(msg=msg, sender_did=agent_did, conn=conn)
    assert ok is False
    assert len(errs) > 0
    conn.close()


# ---------------------------------------------------------------------------
# T11 — MSG5 with sig_field_name="regulatory_signature"
# ---------------------------------------------------------------------------


def test_t11_verify_helper_msg5_regulatory_signature(
    db_path: Path, ed25519_keypair: tuple[bytes, bytes], verify_message_signature
):
    """MSG5 signed by regulator, verified with sig_field_name kwarg."""
    priv, pub = ed25519_keypair
    regulator_did = did_from_pubkey(pub)
    create_governance_tables(db_path)
    conn = _connect(db_path)
    _register_agent(conn, regulator_did, pub)

    msg = RegulatoryDecision(
        session_id="s1",
        approved_bids=["bid-1"],
        rejected_bids=[],
        fairness_score=0.8,
        compliance_flags=[],
        regulatory_signature="ab" * 64,
    )
    canonical = canonical_signed_bytes(msg)
    sig = ed25519.sign(priv, canonical)
    msg.regulatory_signature = sig.hex()

    ok, errs = verify_message_signature(
        msg=msg,
        sender_did=regulator_did,
        conn=conn,
        sig_field_name="regulatory_signature",
    )
    assert ok is True
    assert errs == []
    conn.close()


# ---------------------------------------------------------------------------
# T12 — MSG7 dual-cosig happy path
# ---------------------------------------------------------------------------


def test_t12_verify_helper_msg7_dual_cosig_happy_path(
    db_path: Path, verify_message_signature
):
    """Both speaker and regulator signatures valid over same canonical bytes."""
    spk_priv, spk_pub = ed25519.generate_keypair()
    reg_priv, reg_pub = ed25519.generate_keypair()
    speaker_did = did_from_pubkey(spk_pub)
    regulator_did = did_from_pubkey(reg_pub)

    create_governance_tables(db_path)
    conn = _connect(db_path)
    _register_agent(conn, speaker_did, spk_pub)
    _register_agent(conn, regulator_did, reg_pub)

    msg = LegislativeApproval(
        session_id="s1",
        spec_id="spec-abc",
        speaker_signature="ab" * 64,
        regulator_signature="ab" * 64,
    )
    canonical = canonical_signed_bytes(msg)
    msg.speaker_signature = ed25519.sign(spk_priv, canonical).hex()
    msg.regulator_signature = ed25519.sign(reg_priv, canonical).hex()

    ok1, errs1 = verify_message_signature(
        msg=msg,
        sender_did=speaker_did,
        conn=conn,
        sig_field_name="speaker_signature",
    )
    assert ok1 is True
    assert errs1 == []

    ok2, errs2 = verify_message_signature(
        msg=msg,
        sender_did=regulator_did,
        conn=conn,
        sig_field_name="regulator_signature",
    )
    assert ok2 is True
    assert errs2 == []
    conn.close()


# ---------------------------------------------------------------------------
# T13 — MSG7 with one bad cosig
# ---------------------------------------------------------------------------


def test_t13_verify_helper_msg7_one_bad_cosig(db_path: Path, verify_message_signature):
    """Speaker sig valid, regulator sig from wrong key → second call fails."""
    spk_priv, spk_pub = ed25519.generate_keypair()
    reg_priv, reg_pub = ed25519.generate_keypair()
    wrong_priv, wrong_pub = ed25519.generate_keypair()
    speaker_did = did_from_pubkey(spk_pub)
    regulator_did = did_from_pubkey(reg_pub)

    create_governance_tables(db_path)
    conn = _connect(db_path)
    _register_agent(conn, speaker_did, spk_pub)
    _register_agent(conn, regulator_did, reg_pub)

    msg = LegislativeApproval(
        session_id="s1",
        spec_id="spec-abc",
        speaker_signature="ab" * 64,
        regulator_signature="ab" * 64,
    )
    canonical = canonical_signed_bytes(msg)
    msg.speaker_signature = ed25519.sign(spk_priv, canonical).hex()
    # Regulator signature signed by wrong key
    msg.regulator_signature = ed25519.sign(wrong_priv, canonical).hex()

    ok1, errs1 = verify_message_signature(
        msg=msg,
        sender_did=speaker_did,
        conn=conn,
        sig_field_name="speaker_signature",
    )
    assert ok1 is True
    assert errs1 == []

    ok2, errs2 = verify_message_signature(
        msg=msg,
        sender_did=regulator_did,
        conn=conn,
        sig_field_name="regulator_signature",
    )
    assert ok2 is False
    assert any("verification failed" in e.lower() for e in errs2)
    conn.close()
