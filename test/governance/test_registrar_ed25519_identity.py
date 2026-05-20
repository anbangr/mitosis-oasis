"""Phase 1 — register_agent accepts public_key + verify_identity uses real Ed25519 (TDD).

Test spec T1–T8 plus edge cases.
Coverage target: ≥80%.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from pydantic import ValidationError

from oasis.crypto import ed25519
from oasis.crypto.did import did_from_pubkey
from oasis.governance.clerks.registrar import Registrar
from oasis.governance.messages import IdentityAttestation, canonical_signed_bytes
from oasis.governance.schema import create_governance_tables, seed_constitution

from test.governance.conftest import make_signed_attestation, register_agent_with_key


# ---------------------------------------------------------------------------
# T1 — registry stores public_key
# ---------------------------------------------------------------------------


def test_t1_registry_stores_public_key(governance_db: Path, ed25519_keypair: tuple[bytes, bytes]):
    """T1: register_agent persists public_key in agent_registry."""
    priv, pub = ed25519_keypair
    agent_did = did_from_pubkey(pub)
    reg = Registrar(str(governance_db), "did:oasis:clerk-registrar")
    reg.register_agent(agent_did, "producer", "p1", public_key=pub.hex())

    conn = sqlite3.connect(str(governance_db))
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute(
            "SELECT public_key FROM agent_registry WHERE agent_did = ?",
            (agent_did,),
        ).fetchone()
    finally:
        conn.close()

    assert row is not None, "agent_registry row missing"
    assert row["public_key"] == pub.hex(), "public_key not stored correctly"


# ---------------------------------------------------------------------------
# T2 — IdentityAttestation.signature is exactly 64-byte hex
# ---------------------------------------------------------------------------


def test_t2_signature_exactly_64_byte_hex():
    """T2: 64-byte hex signature succeeds; short/invalid signature raises ValidationError."""
    # Good case — exactly 128 hex chars (64 bytes)
    good = IdentityAttestation(
        session_id="s",
        agent_did="did:key:zX",
        signature="ab" * 64,
        reputation_score=0.5,
        agent_type="producer",
    )
    assert good.signature == "ab" * 64

    # Bad case — too short
    with pytest.raises(ValidationError) as exc_info:
        IdentityAttestation(
            session_id="s",
            agent_did="did:key:zX",
            signature="abc",
            reputation_score=0.5,
            agent_type="producer",
        )
    err = str(exc_info.value)
    assert "128" in err or "pattern" in err.lower()

    # Bad case — uppercase hex (pattern requires lowercase)
    with pytest.raises(ValidationError) as exc_info:
        IdentityAttestation(
            session_id="s",
            agent_did="did:key:zX",
            signature="AB" * 64,
            reputation_score=0.5,
            agent_type="producer",
        )
    assert "pattern" in str(exc_info.value).lower()

    # Bad case — non-hex characters
    with pytest.raises(ValidationError) as exc_info:
        IdentityAttestation(
            session_id="s",
            agent_did="did:key:zX",
            signature="gh" * 64,
            reputation_score=0.5,
            agent_type="producer",
        )
    assert "pattern" in str(exc_info.value).lower()


# ---------------------------------------------------------------------------
# T3 — valid attestation accepted
# ---------------------------------------------------------------------------


def test_t3_valid_attestation_accepted(governance_db: Path, ed25519_keypair: tuple[bytes, bytes]):
    """T3: Real Ed25519 signature + matching did:key + registered public_key → accepted."""
    priv, pub = ed25519_keypair
    agent_did = did_from_pubkey(pub)
    reg = Registrar(str(governance_db), "did:oasis:clerk-registrar")
    reg.open_session("sess-t3", min_reputation=0.1)
    register_agent_with_key(
        governance_db, agent_did, "producer", "Producer T3", pub.hex(), reputation_score=0.5
    )

    msg = make_signed_attestation(
        session_id="sess-t3",
        agent_did=agent_did,
        agent_type="producer",
        reputation_score=0.5,
        private_key=priv,
    )
    result = reg.verify_identity(msg)
    assert result["valid"] is True, f"expected valid=True, got {result}"
    assert result["passed"] is True
    assert result["errors"] == []


# ---------------------------------------------------------------------------
# T4 — wrong-key sig rejected
# ---------------------------------------------------------------------------


def test_t4_wrong_key_signature_rejected(governance_db: Path, ed25519_keypair: tuple[bytes, bytes]):
    """T4: Signature from a different keypair is rejected."""
    priv, pub = ed25519_keypair
    agent_did = did_from_pubkey(pub)
    reg = Registrar(str(governance_db), "did:oasis:clerk-registrar")
    reg.open_session("sess-t4", min_reputation=0.1)
    register_agent_with_key(
        governance_db, agent_did, "producer", "Producer T4", pub.hex(), reputation_score=0.5
    )

    # Sign with a *different* keypair
    other_priv, _other_pub = ed25519.generate_keypair()
    msg = make_signed_attestation(
        session_id="sess-t4",
        agent_did=agent_did,
        agent_type="producer",
        reputation_score=0.5,
        private_key=other_priv,
    )
    result = reg.verify_identity(msg)
    assert result["valid"] is False
    assert result["passed"] is False
    assert any("signature" in e.lower() for e in result["errors"])


# ---------------------------------------------------------------------------
# T5 — unregistered DID rejected
# ---------------------------------------------------------------------------


def test_t5_unregistered_did_rejected(governance_db: Path, ed25519_keypair: tuple[bytes, bytes]):
    """T5: Agent DID with no registry row is rejected (no public_key registered)."""
    priv, pub = ed25519_keypair
    agent_did = did_from_pubkey(pub)
    reg = Registrar(str(governance_db), "did:oasis:clerk-registrar")
    reg.open_session("sess-t5", min_reputation=0.1)
    # NOTE: deliberately do NOT register the agent

    msg = make_signed_attestation(
        session_id="sess-t5",
        agent_did=agent_did,
        agent_type="producer",
        reputation_score=0.5,
        private_key=priv,
    )
    result = reg.verify_identity(msg)
    assert result["valid"] is False
    assert result["passed"] is False
    assert any(
        "public_key" in e.lower() or "registered" in e.lower() for e in result["errors"]
    )


# ---------------------------------------------------------------------------
# T6 — DID/pubkey mismatch rejected
# ---------------------------------------------------------------------------


def test_t6_did_pubkey_mismatch_rejected(
    governance_db: Path, ed25519_keypair: tuple[bytes, bytes]
):
    """T6: Registry public_key does not match the did:key encoding → rejected."""
    priv_a, pub_a = ed25519_keypair
    _priv_b, pub_b = ed25519.generate_keypair()

    # Register agent with pub_a but construct DID from pub_b
    agent_did = did_from_pubkey(pub_b)  # DID derived from pub_b
    reg = Registrar(str(governance_db), "did:oasis:clerk-registrar")
    reg.open_session("sess-t6", min_reputation=0.1)
    register_agent_with_key(
        governance_db,
        agent_did,
        "producer",
        "Producer T6",
        pub_a.hex(),  # registered key is pub_a, not pub_b
        reputation_score=0.5,
    )

    msg = make_signed_attestation(
        session_id="sess-t6",
        agent_did=agent_did,
        agent_type="producer",
        reputation_score=0.5,
        private_key=priv_a,
    )
    result = reg.verify_identity(msg)
    assert result["valid"] is False
    assert result["passed"] is False
    assert any(
        "did:key" in e.lower() or "does not match" in e.lower() for e in result["errors"]
    )


# ---------------------------------------------------------------------------
# T7 — non-did:key DIDs rejected
# ---------------------------------------------------------------------------


def test_t7_non_did_key_rejected(governance_db: Path, ed25519_keypair: tuple[bytes, bytes]):
    """T7: Legacy did:mock: DIDs are explicitly rejected."""
    priv, pub = ed25519_keypair
    agent_did = "did:mock:producer-1"  # legacy format
    reg = Registrar(str(governance_db), "did:oasis:clerk-registrar")
    reg.open_session("sess-t7", min_reputation=0.1)
    # Even if registered with a public_key, the DID format itself is invalid
    register_agent_with_key(
        governance_db, agent_did, "producer", "Producer T7", pub.hex(), reputation_score=0.5
    )

    msg = make_signed_attestation(
        session_id="sess-t7",
        agent_did=agent_did,
        agent_type="producer",
        reputation_score=0.5,
        private_key=priv,
    )
    result = reg.verify_identity(msg)
    assert result["valid"] is False
    assert result["passed"] is False
    assert any("did:key" in e.lower() for e in result["errors"])


# ---------------------------------------------------------------------------
# T8 — tampered field invalidates signature
# ---------------------------------------------------------------------------


def test_t8_tampered_field_invalidates_signature(
    governance_db: Path, ed25519_keypair: tuple[bytes, bytes]
):
    """T8: Mutating a signed field after signing causes verification to fail."""
    priv, pub = ed25519_keypair
    agent_did = did_from_pubkey(pub)
    reg = Registrar(str(governance_db), "did:oasis:clerk-registrar")
    reg.open_session("sess-t8", min_reputation=0.1)
    register_agent_with_key(
        governance_db, agent_did, "producer", "Producer T8", pub.hex(), reputation_score=0.5
    )

    # Sign with reputation_score=0.5
    msg = make_signed_attestation(
        session_id="sess-t8",
        agent_did=agent_did,
        agent_type="producer",
        reputation_score=0.5,
        private_key=priv,
    )
    # Tamper after signing
    msg.reputation_score = 0.9
    result = reg.verify_identity(msg)
    assert result["valid"] is False
    assert result["passed"] is False
    assert any(
        "signature verification failed" in e.lower() for e in result["errors"]
    )


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


def test_edge_register_without_public_key(governance_db: Path, ed25519_keypair: tuple[bytes, bytes]):
    """register_agent without public_key leaves public_key IS NULL;
    verify_identity then rejects with 'No registered public_key' error."""
    priv, pub = ed25519_keypair
    agent_did = did_from_pubkey(pub)
    reg = Registrar(str(governance_db), "did:oasis:clerk-registrar")
    reg.open_session("sess-edge", min_reputation=0.1)
    # Call register_agent WITHOUT public_key (Bundle-0 compat)
    reg.register_agent(agent_did, "producer", "Producer Edge")

    msg = make_signed_attestation(
        session_id="sess-edge",
        agent_did=agent_did,
        agent_type="producer",
        reputation_score=0.5,
        private_key=priv,
    )
    result = reg.verify_identity(msg)
    assert result["valid"] is False
    assert result["passed"] is False
    assert any(
        "public_key" in e.lower() or "registered" in e.lower() for e in result["errors"]
    )


def test_edge_result_dict_has_valid_key(
    governance_db: Path, ed25519_keypair: tuple[bytes, bytes]
):
    """The result dict contains both 'valid' and 'passed' keys (synonyms)."""
    priv, pub = ed25519_keypair
    agent_did = did_from_pubkey(pub)
    reg = Registrar(str(governance_db), "did:oasis:clerk-registrar")
    reg.open_session("sess-valid", min_reputation=0.1)
    register_agent_with_key(
        governance_db, agent_did, "producer", "Producer V", pub.hex(), reputation_score=0.5
    )

    msg = make_signed_attestation(
        session_id="sess-valid",
        agent_did=agent_did,
        agent_type="producer",
        reputation_score=0.5,
        private_key=priv,
    )
    result = reg.verify_identity(msg)
    assert "valid" in result
    assert "passed" in result
    assert result["valid"] == result["passed"]


def test_edge_empty_signature_rejected_at_pydantic_layer():
    """Empty string signature is rejected by Pydantic before verify_identity is called."""
    with pytest.raises(ValidationError) as exc_info:
        IdentityAttestation(
            session_id="s",
            agent_did="did:key:zX",
            signature="",
            reputation_score=0.5,
            agent_type="producer",
        )
    err = str(exc_info.value)
    assert "128" in err or "pattern" in err.lower()
