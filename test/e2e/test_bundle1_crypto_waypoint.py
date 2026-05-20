"""Bundle-1 E2E waypoint — real Ed25519 + canonical-bytes round-trip (TDD).

Exercises every Bundle-1 surface together:
  • clerk did:key migration via ``ensure_clerk_keys``
  • 10 real producer keypairs minted via ``ed25519.generate_keypair()``
  • 10 ``register_agent`` calls with hex pubkeys
  • 6 real ``ed25519.sign(priv, canonical_signed_bytes(msg))`` calls
  • 6 ``log_message(...)` calls writing ``payload = canonical_signed_bytes(msg).hex()``
    + ``signature = msg.signature`` + ``payload_json = msg.model_dump_json()``
  • state-machine identity-to-proposal guard

The post-insert verification step (T4) is the cryptographic round-trip that
exclusively passes when ``payload`` holds canonical bytes hex — under a
plan where ``payload`` carried Pydantic JSON this assertion would fail.
"""

from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
from pathlib import Path
from typing import Generator

import pytest

from oasis.crypto import ed25519
from oasis.crypto.did import did_from_pubkey
from oasis.governance.clerks.bootstrap import ensure_clerk_keys
from oasis.governance.messages import IdentityAttestation, canonical_signed_bytes, log_message
from oasis.governance.schema import create_governance_tables, seed_constitution
from oasis.governance.state_machine import GuardResult, LegislativeState, _guard_identity_to_proposal


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def gov_db(tmp_path: Path) -> Path:
    """Fresh governance DB with tables, constitution, and did:key clerks."""
    db = tmp_path / "gov.db"
    create_governance_tables(db)
    seed_constitution(db)
    # Use isolated keys_dir so parallel runs never collide
    ensure_clerk_keys(db, keys_dir=tmp_path / "clerk_keys")
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


def _register_producer(db_path: Path, did: str, public_key: bytes, reputation_score: float = 0.5) -> None:
    """Register a producer agent with a real Ed25519 public key (hex)."""
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute(
        "INSERT INTO agent_registry "
        "(agent_did, agent_type, display_name, human_principal, reputation_score, active, public_key) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (did, "producer", f"Producer {did}", "test@example.com", reputation_score, 1, public_key.hex()),
    )
    conn.commit()
    conn.close()


def _make_signed_attestation(
    session_id: str, agent_did: str, reputation_score: float, private_key: bytes
) -> IdentityAttestation:
    """Build an ``IdentityAttestation`` and sign it over canonical bytes."""
    msg = IdentityAttestation(
        session_id=session_id,
        agent_did=agent_did,
        signature="ab" * 64,  # placeholder — replaced after canonicalisation
        reputation_score=reputation_score,
        agent_type="producer",
    )
    canonical = canonical_signed_bytes(msg)
    sig = ed25519.sign(private_key, canonical)
    msg.signature = sig.hex()
    return msg


def _insert_session(db_path: Path, session_id: str) -> None:
    """Insert a legislative session row in ``IDENTITY_VERIFICATION`` state."""
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute(
        "INSERT INTO legislative_session (session_id, state, epoch, mission_budget_cap) VALUES (?, ?, ?, ?)",
        (session_id, LegislativeState.IDENTITY_VERIFICATION.value, 0, 1000.0),
    )
    conn.commit()
    conn.close()


# ---------------------------------------------------------------------------
# T1 — 6/10 real-Ed25519 attestations pass guard
# ---------------------------------------------------------------------------


class TestBundleOneCryptoWaypoint:
    """Bundle-1 E2E waypoint (T1–T6)."""

    def test_t1_six_of_ten_real_ed25519_pass_guard(self, gov_db: Path, gov_conn: sqlite3.Connection):
        """T1: 6/10 attestations with real signatures clear quorum_threshold=0.60."""
        session_id = "smoke-bundle1"

        # Mint 10 real producer keypairs and register them
        producers = []
        for _ in range(10):
            priv, pub = ed25519.generate_keypair()
            did = did_from_pubkey(pub)
            _register_producer(gov_db, did, pub)
            producers.append((priv, pub, did))

        _insert_session(gov_db, session_id)

        # Sign and log 6 real attestations
        for priv, _pub, did in producers[:6]:
            att = _make_signed_attestation(session_id, did, 0.5, priv)
            log_message(gov_db, session_id, att, sender_did=did)

        result = _guard_identity_to_proposal(session_id, gov_conn)

        assert isinstance(result, GuardResult)
        assert result.allowed is True, f"Guard blocked with reason: {result.reason}"

    # -----------------------------------------------------------------------
    # T2 — 0/10 attestations fail guard
    # -----------------------------------------------------------------------

    def test_t2_zero_of_ten_attestations_fail_guard(self, gov_db: Path, gov_conn: sqlite3.Connection):
        """T2: 0/10 attestations at quorum_threshold=0.60 → blocked."""
        session_id = "smoke-bundle1-t2"

        for _ in range(10):
            priv, pub = ed25519.generate_keypair()
            did = did_from_pubkey(pub)
            _register_producer(gov_db, did, pub)

        _insert_session(gov_db, session_id)

        result = _guard_identity_to_proposal(session_id, gov_conn)

        assert isinstance(result, GuardResult)
        assert result.allowed is False
        assert "quorum" in result.reason.lower() or "attestation" in result.reason.lower()

    # -----------------------------------------------------------------------
    # T4 — Signature verifiable post-insert via canonical-bytes round-trip
    # -----------------------------------------------------------------------

    def test_t4_signature_verifiable_post_insert(self, gov_db: Path):
        """T4: For every logged row ``ed25519.verify(pub, canonical, sig)`` is True."""
        session_id = "smoke-bundle1-t4"

        producers = []
        for _ in range(10):
            priv, pub = ed25519.generate_keypair()
            did = did_from_pubkey(pub)
            _register_producer(gov_db, did, pub)
            producers.append((priv, pub, did))

        _insert_session(gov_db, session_id)

        msgs = []
        for priv, pub, did in producers[:6]:
            att = _make_signed_attestation(session_id, did, 0.5, priv)
            log_message(gov_db, session_id, att, sender_did=did)
            msgs.append((att, pub, did))

        conn = sqlite3.connect(str(gov_db))
        conn.row_factory = sqlite3.Row
        try:
            rows = conn.execute(
                "SELECT sender_did, payload, signature, payload_json "
                "FROM message_log WHERE session_id = ? AND msg_type = 'IDENTITY_ATTESTATION' "
                "ORDER BY log_id",
                (session_id,),
            ).fetchall()
            assert len(rows) == 6

            for row, (_msg, _pub, _did) in zip(rows, msgs):
                # Look up the producer's public_key from agent_registry
                reg_row = conn.execute(
                    "SELECT public_key FROM agent_registry WHERE agent_did = ?",
                    (row["sender_did"],),
                ).fetchone()
                assert reg_row is not None, f"No public_key for {row['sender_did']}"

                pub_key = bytes.fromhex(reg_row["public_key"])
                canonical = bytes.fromhex(row["payload"])
                sig = bytes.fromhex(row["signature"])

                assert ed25519.verify(pub_key, canonical, sig) is True
        finally:
            conn.close()

    # -----------------------------------------------------------------------
    # T5 — payload_json preserves Pydantic shape
    # -----------------------------------------------------------------------

    def test_t5_payload_json_preserves_pydantic_shape(self, gov_db: Path):
        """T5: ``json.loads(payload_json)['agent_did'] == msg.agent_did`` for all rows."""
        session_id = "smoke-bundle1-t5"

        producers = []
        for _ in range(10):
            priv, pub = ed25519.generate_keypair()
            did = did_from_pubkey(pub)
            _register_producer(gov_db, did, pub)
            producers.append((priv, pub, did))

        _insert_session(gov_db, session_id)

        msgs = []
        for priv, _pub, did in producers[:6]:
            att = _make_signed_attestation(session_id, did, 0.5, priv)
            log_message(gov_db, session_id, att, sender_did=did)
            msgs.append(att)

        conn = sqlite3.connect(str(gov_db))
        conn.row_factory = sqlite3.Row
        try:
            rows = conn.execute(
                "SELECT payload_json FROM message_log "
                "WHERE session_id = ? AND msg_type = 'IDENTITY_ATTESTATION' "
                "ORDER BY log_id",
                (session_id,),
            ).fetchall()
            assert len(rows) == 6

            for row, msg in zip(rows, msgs):
                parsed = json.loads(row["payload_json"])
                assert parsed["agent_did"] == msg.agent_did
        finally:
            conn.close()

    # -----------------------------------------------------------------------
    # T6 — clerk did:key migration is observable
    # -----------------------------------------------------------------------

    def test_t6_clerk_did_key_migration_observable(self, gov_db: Path):
        """T6: All four clerk rows have ``agent_did`` matching ``^did:key:z``."""
        conn = sqlite3.connect(str(gov_db))
        conn.row_factory = sqlite3.Row
        try:
            rows = conn.execute(
                "SELECT agent_did FROM agent_registry WHERE agent_type = 'clerk'"
            ).fetchall()
            assert len(rows) == 4
            for row in rows:
                assert row["agent_did"].startswith("did:key:z")

            # Explicitly assert no did:oasis:clerk-* survives
            oasis_count = conn.execute(
                "SELECT COUNT(*) FROM agent_registry WHERE agent_did LIKE 'did:oasis:clerk-%'"
            ).fetchone()[0]
            assert oasis_count == 0
        finally:
            conn.close()


# ---------------------------------------------------------------------------
# T3 — Bundle-0 waypoint still passes
# ---------------------------------------------------------------------------


def test_t3_bundle_zero_waypoint_still_passes():
    """T3: The existing Bundle-0 e2e test suite passes after Feature-8 rewrite."""
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "test/e2e/test_full_protocol_smoke.py", "-v"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (
        f"Bundle-0 tests failed (rc={result.returncode}):\n"
        f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )
