"""T14–T17 — Clerk crypto wiring (Speaker MSG3/MSG7, Regulator MSG4/MSG5,
Codifier MSG6).

These tests exercise the endpoints and clerk classes once
``verify_message_signature`` is wired in.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from oasis.api import app
from oasis.crypto import ed25519
from oasis.crypto.did import did_from_pubkey
from oasis.governance.clerks.codifier import Codifier
from oasis.governance.clerks.regulator import Regulator
from oasis.governance.clerks.speaker import Speaker
from oasis.governance.messages import (
    CodedContractSpec,
    DAGProposal,
    LegislativeApproval,
    TaskBid,
    canonical_signed_bytes,
)

client = TestClient(app)


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


def _make_signed_dag_proposal(
    session_id: str, proposer_did: str, private_key: bytes
) -> DAGProposal:
    msg = DAGProposal(
        session_id=session_id,
        proposer_did=proposer_did,
        dag_spec={"nodes": [{"node_id": "n1", "label": "A"}], "edges": []},
        rationale="test",
        token_budget_total=100.0,
        deadline_ms=60000,
        signature="ab" * 64,
    )
    canonical = canonical_signed_bytes(msg)
    msg.signature = ed25519.sign(private_key, canonical).hex()
    return msg


def _make_signed_task_bid(
    session_id: str, bidder_did: str, private_key: bytes
) -> TaskBid:
    msg = TaskBid(
        session_id=session_id,
        task_node_id="node-1",
        bidder_did=bidder_did,
        service_id="svc-1",
        proposed_code_hash="a1b2c3d4e5f6g7h8",
        stake_amount=1.0,
        estimated_latency_ms=5000,
        quoted_price=1.0,
        capability_match=0.5,
        pop_tier_acceptance=2,
        signature="ab" * 64,
    )
    canonical = canonical_signed_bytes(msg)
    msg.signature = ed25519.sign(private_key, canonical).hex()
    return msg


def _make_signed_coded_contract_spec(
    session_id: str, clerk_did: str, private_key: bytes
) -> CodedContractSpec:
    msg = CodedContractSpec(
        session_id=session_id,
        collaboration_contract_spec={"a": 1},
        guardian_module_spec={"b": 2},
        verification_module_spec={"c": 3},
        gate_module_spec={"d": 4},
        service_contract_specs={"e": 5},
        validation_proof="proof-123",
        signature="ab" * 64,
    )
    canonical = canonical_signed_bytes(msg)
    msg.signature = ed25519.sign(private_key, canonical).hex()
    return msg


def _make_signed_legislative_approval(
    session_id: str, spec_id: str, speaker_priv: bytes, regulator_priv: bytes
) -> LegislativeApproval:
    msg = LegislativeApproval(
        session_id=session_id,
        spec_id=spec_id,
        speaker_signature="ab" * 64,
        regulator_signature="ab" * 64,
    )
    canonical = canonical_signed_bytes(msg)
    msg.speaker_signature = ed25519.sign(speaker_priv, canonical).hex()
    msg.regulator_signature = ed25519.sign(regulator_priv, canonical).hex()
    return msg


# ---------------------------------------------------------------------------
# T14 — Speaker rejects malformed-sig MSG3
# ---------------------------------------------------------------------------


def test_t14_speaker_rejects_malformed_sig_msg3():
    """DAGProposal with signature='placeholder' raises ValidationError
    (non-hex 128-char pattern) before reaching Speaker."""
    with pytest.raises(ValidationError):
        DAGProposal(
            session_id="s14",
            proposer_did="did:key:zTest",
            dag_spec={"nodes": [{"node_id": "n1", "label": "A"}], "edges": []},
            rationale="test",
            token_budget_total=100.0,
            deadline_ms=60000,
            signature="placeholder",
        )


# ---------------------------------------------------------------------------
# T15 — Regulator rejects MSG4 with wrong-key sig
# ---------------------------------------------------------------------------


def test_t15_regulator_rejects_msg4_wrong_key_sig(governance_db: Path):
    """MSG4 with correctly-formatted but wrong signature → bid rejected,
    no row in bid table."""
    db_path = governance_db
    priv, pub = ed25519.generate_keypair()
    bidder_did = did_from_pubkey(pub)
    conn = _connect(db_path)
    _register_agent(conn, bidder_did, pub)

    # Set up session + proposal + dag_node
    conn.execute(
        "INSERT INTO legislative_session (session_id, state, epoch) VALUES (?, ?, ?)",
        ("s15", "BIDDING_OPEN", 0),
    )
    conn.execute(
        "INSERT INTO proposal (proposal_id, session_id, proposer_did, dag_spec, "
        "token_budget_total, deadline_ms, status) VALUES (?, ?, ?, ?, ?, ?, ?)",
        ("prop-15", "s15", bidder_did, "{}", 1000.0, 60000, "submitted"),
    )
    conn.execute(
        "INSERT INTO dag_node (node_id, proposal_id, label, service_id, pop_tier, "
        "token_budget, timeout_ms) VALUES (?, ?, ?, ?, ?, ?, ?)",
        ("node-1", "prop-15", "Task", "svc-1", 2, 500.0, 60000),
    )
    conn.commit()
    conn.close()

    # Build MSG4 with a signature from a *different* key
    wrong_priv, _ = ed25519.generate_keypair()
    msg4 = _make_signed_task_bid("s15", bidder_did, wrong_priv)

    regulator = Regulator(str(db_path), "did:key:zRegulatorTest")
    result = regulator.receive_bid("s15", msg4)

    assert result["passed"] is False
    assert any("verification failed" in e.lower() for e in result["errors"])

    # No row in bid table
    conn = _connect(db_path)
    count = conn.execute(
        "SELECT COUNT(*) FROM bid WHERE session_id = ?", ("s15",)
    ).fetchone()[0]
    conn.close()
    assert count == 0


# ---------------------------------------------------------------------------
# T16 — Codifier signs MSG6 with persisted key
# ---------------------------------------------------------------------------


def test_t16_codifier_signs_msg6_with_persisted_key(governance_db: Path):
    """Codifier emits MSG6 with a valid Ed25519 signature over canonical bytes."""
    db_path = governance_db

    # We need a codifier with a real keypair.  In the implementation,
    # ensure_clerk_keys will provide this.  For the test we simulate it
    # by generating a keypair and registering it as the codifier clerk.
    cod_priv, cod_pub = ed25519.generate_keypair()
    codifier_did = did_from_pubkey(cod_pub)

    conn = _connect(db_path)
    conn.execute(
        "INSERT OR IGNORE INTO legislative_session (session_id, state, epoch) "
        "VALUES (?, ?, ?)",
        ("s16", "CODIFICATION", 0),
    )
    conn.execute(
        "INSERT OR REPLACE INTO agent_registry "
        "(agent_did, agent_type, display_name, human_principal, public_key) "
        "VALUES (?, ?, ?, ?, ?)",
        (codifier_did, "clerk", "Codifier", "platform@mitosis.dev", cod_pub.hex()),
    )
    conn.execute(
        "UPDATE clerk_registry SET agent_did = ? WHERE clerk_role = 'codifier'",
        (codifier_did,),
    )
    conn.commit()
    conn.close()

    codifier = Codifier(str(db_path), codifier_did, private_key=cod_priv)

    proposal = DAGProposal(
        session_id="s16",
        proposer_did="did:key:zProposer",
        dag_spec={"nodes": [{"node_id": "n1", "label": "A"}], "edges": []},
        rationale="test",
        token_budget_total=100.0,
        deadline_ms=60000,
    )

    msg6 = codifier.compile_spec("s16", proposal, [])

    # Signature must be non-empty
    assert hasattr(msg6, "signature")
    assert msg6.signature is not None
    assert len(msg6.signature) == 128  # 64 bytes hex

    # Cryptographic verification
    canonical = canonical_signed_bytes(msg6)
    assert ed25519.verify(cod_pub, canonical, bytes.fromhex(msg6.signature)) is True


# ---------------------------------------------------------------------------
# T17 — Speaker MSG7 dual-cosign happy path
# ---------------------------------------------------------------------------


def test_t17_speaker_msg7_dual_cosign_happy_path(governance_db: Path):
    """MSG7 with valid speaker + regulator signatures → both helper calls
    return (True, []) and state advances."""
    db_path = governance_db

    spk_priv, spk_pub = ed25519.generate_keypair()
    reg_priv, reg_pub = ed25519.generate_keypair()
    speaker_did = did_from_pubkey(spk_pub)
    regulator_did = did_from_pubkey(reg_pub)

    conn = _connect(db_path)
    # Update clerk_registry to use real did:key clerks
    for role, did, pub in [
        ("speaker", speaker_did, spk_pub),
        ("regulator", regulator_did, reg_pub),
    ]:
        conn.execute(
            "INSERT OR REPLACE INTO agent_registry "
            "(agent_did, agent_type, display_name, human_principal, public_key) "
            "VALUES (?, ?, ?, ?, ?)",
            (did, "clerk", role.title(), "platform@mitosis.dev", pub.hex()),
        )
        conn.execute(
            "UPDATE clerk_registry SET agent_did = ? WHERE clerk_role = ?",
            (did, role),
        )

    # Create session in AWAITING_APPROVAL state
    conn.execute(
        "INSERT INTO legislative_session (session_id, state, epoch) VALUES (?, ?, ?)",
        ("s17", "AWAITING_APPROVAL", 0),
    )
    conn.commit()
    conn.close()

    msg7 = _make_signed_legislative_approval("s17", "spec-abc", spk_priv, reg_priv)

    # Verify both signatures using the helper (imported at top)
    from oasis.crypto._signing import verify_message_signature

    conn = _connect(db_path)
    ok1, errs1 = verify_message_signature(
        msg=msg7,
        sender_did=speaker_did,
        conn=conn,
        sig_field_name="speaker_signature",
    )
    ok2, errs2 = verify_message_signature(
        msg=msg7,
        sender_did=regulator_did,
        conn=conn,
        sig_field_name="regulator_signature",
    )
    conn.close()

    assert ok1 is True
    assert errs1 == []
    assert ok2 is True
    assert errs2 == []

    # State advances via Speaker.issue_approval (or endpoint)
    speaker = Speaker(str(db_path), speaker_did, private_key=spk_priv)
    result = speaker.issue_approval("s17", "spec-abc")
    assert result.get("error") is None
    assert result["speaker_signature"] is not None
