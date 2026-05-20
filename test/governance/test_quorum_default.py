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
"""Tests for quorum_threshold spec §1.7 — value must be 0.60.

Implements the test spec from bundle-0 bug-fix (Red phase — tests MUST fail
before implementation).

T1  — seeded constitution stores SPEC_QUORUM_THRESHOLD (0.60).
T2  — 6/10 producer attestations clear the 0.60 quorum.
T3  — 5/10 producer attestations are below the 0.60 quorum; request denied.

Edge cases (spec §1.7):
    N=1, 1 attestation  → quorum met   (ceil(0.60×1) = 1)
    N=3, 2 attestations → quorum met   (2/3 = 0.667 ≥ 0.60)
    N=3, 1 attestation  → quorum NOT met (1/3 = 0.333 < 0.60)
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from oasis.governance.clerks.registrar import Registrar
from oasis.governance.messages import IdentityAttestation
from oasis.crypto import ed25519
from oasis.crypto.did import did_from_pubkey
from oasis.governance.messages import canonical_signed_bytes
from oasis.governance.schema import _clerk_keypair

SPEC_QUORUM_THRESHOLD = 0.60


# ---------------------------------------------------------------------------
# T1 — Seeded constitution must return 0.60
# ---------------------------------------------------------------------------


def test_t1_seeded_quorum_threshold_is_spec_value(governance_db: Path):
    """T1: seed_constitution must store SPEC_QUORUM_THRESHOLD (0.60)."""
    conn = sqlite3.connect(str(governance_db))
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute(
            "SELECT param_value FROM constitution WHERE param_name = 'quorum_threshold'"
        ).fetchone()
    finally:
        conn.close()
    assert row is not None, "quorum_threshold row is missing from constitution"
    assert row["param_value"] == pytest.approx(SPEC_QUORUM_THRESHOLD), (
        f"Expected quorum_threshold={SPEC_QUORUM_THRESHOLD}, got {row['param_value']!r}"
    )


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _open_session(
    governance_db: Path, session_id: str, num_producers: int
) -> tuple[Registrar, list[tuple[str, bytes]], dict[str, bytes]]:
    """Register num_producers in agent_registry and open a session. Returns (reg, producers, clerk_privs)."""
    reg = Registrar(
        str(governance_db), "did:key:z6Mkkwz2P6pxvfqPxgdssMRZ9UNThiuMueGdV4awUacowDLd"
    )
    reg.open_session(session_id, min_reputation=0.1)

    producers = []
    clerk_privs = {}
    conn = sqlite3.connect(str(governance_db))
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        for i in range(1, num_producers + 1):
            priv, pub = ed25519.generate_keypair()
            did = did_from_pubkey(pub)
            producers.append((did, priv))
            conn.execute(
                "INSERT OR IGNORE INTO agent_registry "
                "(agent_did, agent_type, display_name, human_principal, reputation_score, public_key) "
                "VALUES (?, 'producer', ?, 'test@example.com', 0.5, ?)",
                (did, f"Producer {i}", pub.hex()),
            )

        for role in ("speaker", "regulator", "codifier"):
            priv, pub, did = _clerk_keypair(role)
            clerk_privs[role] = (did, priv)

        conn.commit()
    finally:
        conn.close()
    return reg, producers, clerk_privs


def _attest(
    reg: Registrar,
    session_id: str,
    agent_did: str,
    private_key: bytes,
    agent_type: str = "producer",
) -> None:
    """Submit a passing identity attestation for agent_did."""
    att = IdentityAttestation(
        session_id=session_id,
        agent_did=agent_did,
        signature="ab" * 64,
        reputation_score=0.5,
        agent_type=agent_type,
    )
    att.signature = ed25519.sign(private_key, canonical_signed_bytes(att)).hex()
    res = reg.verify_identity(att)
    assert res["passed"] is True, res


def _attest_clerks(
    reg: Registrar, session_id: str, clerk_privs: dict[str, bytes]
) -> None:
    """Attest the three non-registrar clerks required for quorum."""
    for role in ("speaker", "regulator", "codifier"):
        did, priv = clerk_privs[role]
        _attest(reg, session_id, did, priv, "clerk")


# ---------------------------------------------------------------------------
# T2 — 6/10 clears quorum at 0.60
# ---------------------------------------------------------------------------


def test_t2_six_of_ten_clears_quorum(governance_db: Path):
    """T2: 6 of 10 producers (60%) satisfies the 0.60 quorum threshold."""
    reg, producers, clerks = _open_session(governance_db, "sess-t2", num_producers=10)
    _attest_clerks(reg, "sess-t2", clerks)
    for i in range(0, 6):
        did, priv = producers[i]
        _attest(reg, "sess-t2", did, priv)
    assert reg.check_quorum("sess-t2") is True


# ---------------------------------------------------------------------------
# T3 — 5/10 fails quorum at 0.60
# ---------------------------------------------------------------------------


def test_t3_five_of_ten_fails_quorum(governance_db: Path):
    """T3: 5 of 10 producers (50%) is below the 0.60 quorum threshold."""
    reg, producers, clerks = _open_session(governance_db, "sess-t3", num_producers=10)
    _attest_clerks(reg, "sess-t3", clerks)
    for i in range(0, 5):
        did, priv = producers[i]
        _attest(reg, "sess-t3", did, priv)
    assert reg.check_quorum("sess-t3") is False


# ---------------------------------------------------------------------------
# Edge cases (spec §1.7)
# ---------------------------------------------------------------------------


def test_edge_n1_single_voter_meets_quorum(governance_db: Path):
    """Edge N=1: ceil(0.60×1)=1 — the sole producer suffices."""
    reg, producers, clerks = _open_session(governance_db, "sess-n1", num_producers=1)
    _attest_clerks(reg, "sess-n1", clerks)
    did, priv = producers[0]
    _attest(reg, "sess-n1", did, priv)
    assert reg.check_quorum("sess-n1") is True


def test_edge_n3_two_attestations_meet_quorum(governance_db: Path):
    """Edge N=3, 2 attested (0.667 ≥ 0.60): quorum met."""
    reg, producers, clerks = _open_session(governance_db, "sess-n3p", num_producers=3)
    _attest_clerks(reg, "sess-n3p", clerks)
    for i in range(0, 2):
        did, priv = producers[i]
        _attest(reg, "sess-n3p", did, priv)
    assert reg.check_quorum("sess-n3p") is True


def test_edge_n3_one_attestation_fails_quorum(governance_db: Path):
    """Edge N=3, 1 attested (0.333 < 0.60): quorum not met."""
    reg, producers, clerks = _open_session(governance_db, "sess-n3f", num_producers=3)
    _attest_clerks(reg, "sess-n3f", clerks)
    did, priv = producers[0]
    _attest(reg, "sess-n3f", did, priv)
    assert reg.check_quorum("sess-n3f") is False
