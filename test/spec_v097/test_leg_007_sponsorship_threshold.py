# =========== Copyright 2023 @ CAMEL-AI.org. All Rights Reserved. ===========
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
# =========== Copyright 2023 @ CAMEL-AI.org. All Rights Reserved. ===========
r"""T1–T4 + edge cases: MSG3 sponsorship threshold validation (spec §4).

These tests assert that:

* ``DAGProposal`` carries a ``sponsor_signatures`` field with an empty-list
  default;
* ``Speaker.validate_sponsorship`` enforces the constitutional
  ``sponsorship_min`` threshold (default 5);
* Duplicate signers are de-duplicated;
* Inactive, unknown, and zero-reputation signers are silently skipped;
* Malformed hex strings never crash the validator.

All cases are **RED** until the implementation phase adds the field and
method.
"""

from __future__ import annotations

import hashlib
import sqlite3
from pathlib import Path

import pytest

from oasis.crypto import ed25519
from oasis.crypto.did import did_from_pubkey
from oasis.governance.clerks.speaker import Speaker
from oasis.governance.messages import DAGProposal
from oasis.governance.schema import create_governance_tables, seed_constitution
from pydantic_core import PydanticUndefined


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_speaker(db_path: Path) -> Speaker:
    """Return a Speaker instance backed by *db_path*."""
    return Speaker(db_path=str(db_path), clerk_did="did:mock:speaker")


def _register_producer(
    conn: sqlite3.Connection,
    agent_did: str,
    public_key: bytes,
    *,
    active: int = 1,
    reputation_score: float = 0.5,
) -> None:
    """Insert a producer row into agent_registry."""
    conn.execute(
        "INSERT OR IGNORE INTO agent_registry "
        "(agent_did, agent_type, display_name, human_principal, public_key, active, reputation_score) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (
            agent_did,
            "producer",
            "Test Agent",
            "test@example.com",
            public_key.hex(),
            active,
            reputation_score,
        ),
    )
    conn.commit()


def _sign_payload(private_key: bytes, payload_hex: str) -> str:
    """Sign *payload_hex* (interpreted as hex bytes) and return sig hex."""
    payload = bytes.fromhex(payload_hex)
    sig = ed25519.sign(private_key, payload)
    return sig.hex()


def _seed_db(db_path: Path) -> None:
    """Provision tables and seed constitution (includes ``sponsorship_min``)."""
    create_governance_tables(str(db_path))
    seed_constitution(str(db_path))


# ---------------------------------------------------------------------------
# T1 — DAGProposal field exists
# ---------------------------------------------------------------------------


def test_t1_dag_proposal_sponsor_signatures_field():
    r"""T1: DAGProposal declares ``sponsor_signatures`` with an empty-list default."""
    assert "sponsor_signatures" in DAGProposal.model_fields, (
        "DAGProposal is missing the sponsor_signatures field"
    )
    field_info = DAGProposal.model_fields["sponsor_signatures"]
    assert field_info.is_required() is False, "sponsor_signatures must not be required"
    # default_factory=list → default is PydanticUndefined, factory produces []
    if field_info.default is PydanticUndefined:
        assert field_info.default_factory is not None
        assert field_info.default_factory() == []
    else:
        assert field_info.default == []


# ---------------------------------------------------------------------------
# T2 — Below-threshold rejected
# ---------------------------------------------------------------------------


def test_t2_below_threshold_rejected(tmp_path: Path) -> None:
    r"""T2: 4 distinct valid signatures → ``validate_sponsorship`` returns valid=False."""
    db_path = tmp_path / "gov.db"
    _seed_db(db_path)
    speaker = _make_speaker(db_path)

    payload_hex = "deadbeef" * 8  # 64 bytes

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")

    sponsor_sigs: list[dict] = []
    for i in range(4):
        seed = hashlib.sha256(f"sponsor-{i}".encode()).digest()
        priv, pub = ed25519.keypair_from_seed(seed)
        did = did_from_pubkey(pub)
        _register_producer(conn, did, pub)
        sig = _sign_payload(priv, payload_hex)
        sponsor_sigs.append({"signer_did": did, "signature_hex": sig})

    conn.close()

    result = speaker.validate_sponsorship(
        session_id="s1",
        payload_hex=payload_hex,
        sponsor_signatures=sponsor_sigs,
    )
    assert result["valid"] is False
    assert "5" in result["reason"], (
        f'Expected reason to mention threshold "5", got: {result["reason"]}'
    )


# ---------------------------------------------------------------------------
# T3 — At-threshold accepted
# ---------------------------------------------------------------------------


def test_t3_at_threshold_accepted(tmp_path: Path) -> None:
    r"""T3: 5 distinct valid signatures → valid=True, distinct_count == 5."""
    db_path = tmp_path / "gov.db"
    _seed_db(db_path)
    speaker = _make_speaker(db_path)

    payload_hex = "cafebabe" * 8

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")

    sponsor_sigs: list[dict] = []
    for i in range(5):
        seed = hashlib.sha256(f"sponsor-{i}".encode()).digest()
        priv, pub = ed25519.keypair_from_seed(seed)
        did = did_from_pubkey(pub)
        _register_producer(conn, did, pub)
        sig = _sign_payload(priv, payload_hex)
        sponsor_sigs.append({"signer_did": did, "signature_hex": sig})

    conn.close()

    result = speaker.validate_sponsorship(
        session_id="s1",
        payload_hex=payload_hex,
        sponsor_signatures=sponsor_sigs,
    )
    assert result["valid"] is True
    assert result["distinct_count"] == 5


# ---------------------------------------------------------------------------
# T4 — Duplicate sponsors rejected
# ---------------------------------------------------------------------------


def test_t4_duplicate_sponsors_rejected(tmp_path: Path) -> None:
    r"""T4: 5 signatures from only 3 distinct DIDs → valid=False."""
    db_path = tmp_path / "gov.db"
    _seed_db(db_path)
    speaker = _make_speaker(db_path)

    payload_hex = "feedface" * 8

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")

    # 3 distinct signers
    signers: list[tuple[str, bytes]] = []
    for i in range(3):
        seed = hashlib.sha256(f"dup-sponsor-{i}".encode()).digest()
        priv, pub = ed25519.keypair_from_seed(seed)
        did = did_from_pubkey(pub)
        _register_producer(conn, did, pub)
        signers.append((did, priv))

    # 5 signatures: [0, 0, 1, 1, 2]
    sponsor_sigs: list[dict] = []
    for idx in (0, 0, 1, 1, 2):
        did, priv = signers[idx]
        sig = _sign_payload(priv, payload_hex)
        sponsor_sigs.append({"signer_did": did, "signature_hex": sig})

    conn.close()

    result = speaker.validate_sponsorship(
        session_id="s1",
        payload_hex=payload_hex,
        sponsor_signatures=sponsor_sigs,
    )
    assert result["valid"] is False
    assert result.get("distinct_count", 0) < 5


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


def test_inactive_signer_skipped(tmp_path: Path) -> None:
    """Inactive (active=0) agents are silently skipped during validation."""
    db_path = tmp_path / "gov.db"
    _seed_db(db_path)
    speaker = _make_speaker(db_path)

    payload_hex = "babebabe" * 8

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")

    # 4 active + 1 inactive
    sponsor_sigs: list[dict] = []
    for i in range(5):
        seed = hashlib.sha256(f"edge-sponsor-{i}".encode()).digest()
        priv, pub = ed25519.keypair_from_seed(seed)
        did = did_from_pubkey(pub)
        active = 0 if i == 4 else 1
        _register_producer(conn, did, pub, active=active)
        sig = _sign_payload(priv, payload_hex)
        sponsor_sigs.append({"signer_did": did, "signature_hex": sig})

    conn.close()

    result = speaker.validate_sponsorship(
        session_id="s1",
        payload_hex=payload_hex,
        sponsor_signatures=sponsor_sigs,
    )
    assert result["valid"] is False
    assert result.get("distinct_count", 0) == 4


def test_zero_reputation_rejected(tmp_path: Path) -> None:
    """Zero-reputation producers are rejected even with a cryptographically valid sig."""
    db_path = tmp_path / "gov.db"
    _seed_db(db_path)
    speaker = _make_speaker(db_path)

    payload_hex = "deadbabe" * 8

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")

    sponsor_sigs: list[dict] = []
    for i in range(5):
        seed = hashlib.sha256(f"zero-rep-{i}".encode()).digest()
        priv, pub = ed25519.keypair_from_seed(seed)
        did = did_from_pubkey(pub)
        rep = 0.0 if i == 0 else 0.5
        _register_producer(conn, did, pub, reputation_score=rep)
        sig = _sign_payload(priv, payload_hex)
        sponsor_sigs.append({"signer_did": did, "signature_hex": sig})

    conn.close()

    result = speaker.validate_sponsorship(
        session_id="s1",
        payload_hex=payload_hex,
        sponsor_signatures=sponsor_sigs,
    )
    assert result["valid"] is False
    assert result.get("distinct_count", 0) == 4


def test_malformed_hex_handled(tmp_path: Path) -> None:
    """Malformed hex in signature_hex or payload_hex is handled without crashing."""
    db_path = tmp_path / "gov.db"
    _seed_db(db_path)
    speaker = _make_speaker(db_path)

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")

    # 1 valid signer
    seed = hashlib.sha256(b"valid-signer").digest()
    priv, pub = ed25519.keypair_from_seed(seed)
    did = did_from_pubkey(pub)
    _register_producer(conn, did, pub)
    valid_sig = _sign_payload(priv, "cafebabe" * 8)

    conn.close()

    # malformed payload_hex
    result = speaker.validate_sponsorship(
        session_id="s1",
        payload_hex="not-hex!!!",
        sponsor_signatures=[{"signer_did": did, "signature_hex": valid_sig}],
    )
    assert result["valid"] is False

    # malformed signature_hex
    result = speaker.validate_sponsorship(
        session_id="s1",
        payload_hex="cafebabe" * 8,
        sponsor_signatures=[{"signer_did": did, "signature_hex": "zzzz"}],
    )
    assert result["valid"] is False

    # missing signature_hex key in dict
    result = speaker.validate_sponsorship(
        session_id="s1",
        payload_hex="cafebabe" * 8,
        sponsor_signatures=[{"signer_did": did}],
    )
    assert result["valid"] is False


def test_nonexistent_signer_skipped(tmp_path: Path) -> None:
    """Signatures from DIDs not in the registry are silently skipped."""
    db_path = tmp_path / "gov.db"
    _seed_db(db_path)
    speaker = _make_speaker(db_path)

    payload_hex = "cafebabe" * 8

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")

    # Only register 4 out of 5 signers
    sponsor_sigs: list[dict] = []
    for i in range(5):
        seed = hashlib.sha256(f"missing-{i}".encode()).digest()
        priv, pub = ed25519.keypair_from_seed(seed)
        did = did_from_pubkey(pub)
        if i < 4:
            _register_producer(conn, did, pub)
        sig = _sign_payload(priv, payload_hex)
        sponsor_sigs.append({"signer_did": did, "signature_hex": sig})

    conn.close()

    result = speaker.validate_sponsorship(
        session_id="s1",
        payload_hex=payload_hex,
        sponsor_signatures=sponsor_sigs,
    )
    assert result["valid"] is False
    assert result.get("distinct_count", 0) == 4
