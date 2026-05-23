# Licensed to the Apache Software Foundation (ASF) under one
# or more contributor license agreements.  See the NOTICE file
# distributed with this work for additional information
# regarding copyright ownership.  The ASF licenses this file
# to you under the Apache License, Version 2.0 (the
# "License"); you may not use this file except in compliance
# with the License.  You may obtain a copy of the License at
#
#   http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing,
# software distributed under the License is distributed on an
# "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY
# KIND, either express or implied.  See the License for the
# specific language governing permissions and limitations
# under the License.
"""Unit tests for petition_trigger (Bundle 5 Phase 5.1)."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from oasis.governance.scheduler.petition_trigger import (
    accumulate_signature,
    check_threshold,
    fire_petition,
)
from oasis.governance.schema import create_governance_tables


@pytest.fixture
def gov_db(tmp_path: Path) -> str:
    db = tmp_path / "g.db"
    create_governance_tables(str(db))
    return str(db)


def _seed_petition(db_path: str, petition_id: str = "pet-test-001") -> None:
    """Insert a petition row."""
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            "INSERT INTO petition (petition_id, title, rationale, proposed_mission) "
            "VALUES (?, ?, ?, ?)",
            (petition_id, "Test Petition", "Rationale", "Mission X"),
        )
        conn.commit()
    finally:
        conn.close()


def _seed_producers(
    db_path: str, n: int, active: int = 1, offset: int = 0
) -> list[str]:
    """Insert ``n`` producer agents and return their DIDs.

    ``offset`` lets a single test seed two disjoint cohorts without
    DID collisions.
    """
    conn = sqlite3.connect(db_path)
    try:
        dids = []
        for i in range(offset, offset + n):
            did = f"did:mock:producer-{i}"
            dids.append(did)
            conn.execute(
                "INSERT INTO agent_registry "
                "(agent_did, agent_type, display_name, active) "
                "VALUES (?, 'producer', ?, ?)",
                (did, f"Producer {i}", active),
            )
        conn.commit()
        return dids
    finally:
        conn.close()


def _seed_signature(
    db_path: str,
    petition_id: str,
    signer_did: str,
    signature_hex: str = "aa" * 32,
) -> None:
    """Insert a petition signature directly (bypassing accumulate_signature)."""
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            "INSERT INTO petition_signature (petition_id, signer_did, signature_hex) "
            "VALUES (?, ?, ?)",
            (petition_id, signer_did, signature_hex),
        )
        conn.commit()
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# accumulate_signature
# ---------------------------------------------------------------------------


def test_accumulate_signature_inserts_row(gov_db: str) -> None:
    _seed_petition(gov_db)
    accumulate_signature(
        petition_id="pet-test-001",
        signer_did="did:mock:producer-0",
        signature_hex="aa" * 32,
        db_path=gov_db,
    )
    conn = sqlite3.connect(gov_db)
    rows = conn.execute(
        "SELECT petition_id, signer_did, signature_hex FROM petition_signature"
    ).fetchall()
    conn.close()
    assert rows == [("pet-test-001", "did:mock:producer-0", "aa" * 32)]


def test_accumulate_signature_rejects_duplicate_signer(gov_db: str) -> None:
    """Same (petition_id, signer_did) raises sqlite3.IntegrityError."""
    _seed_petition(gov_db)
    accumulate_signature(
        petition_id="pet-test-001",
        signer_did="did:mock:producer-0",
        signature_hex="aa" * 32,
        db_path=gov_db,
    )
    with pytest.raises(sqlite3.IntegrityError):
        accumulate_signature(
            petition_id="pet-test-001",
            signer_did="did:mock:producer-0",
            signature_hex="bb" * 32,
            db_path=gov_db,
        )


def test_accumulate_signature_allows_different_signers(gov_db: str) -> None:
    _seed_petition(gov_db)
    accumulate_signature(
        petition_id="pet-test-001",
        signer_did="did:mock:producer-0",
        signature_hex="aa" * 32,
        db_path=gov_db,
    )
    accumulate_signature(
        petition_id="pet-test-001",
        signer_did="did:mock:producer-1",
        signature_hex="bb" * 32,
        db_path=gov_db,
    )
    conn = sqlite3.connect(gov_db)
    count = conn.execute(
        "SELECT COUNT(*) FROM petition_signature WHERE petition_id = 'pet-test-001'"
    ).fetchone()[0]
    conn.close()
    assert count == 2


# ---------------------------------------------------------------------------
# check_threshold
# ---------------------------------------------------------------------------


def test_check_threshold_false_when_no_signatures(gov_db: str) -> None:
    _seed_petition(gov_db)
    _seed_producers(gov_db, 10)
    assert check_threshold(petition_id="pet-test-001", db_path=gov_db) is False


def test_check_threshold_false_below_threshold(gov_db: str) -> None:
    """1/10 = 0.10 < 0.20."""
    _seed_petition(gov_db)
    dids = _seed_producers(gov_db, 10)
    _seed_signature(gov_db, "pet-test-001", dids[0])
    assert check_threshold(petition_id="pet-test-001", db_path=gov_db) is False


def test_check_threshold_true_at_threshold(gov_db: str) -> None:
    """2/10 = 0.20 >= 0.20."""
    _seed_petition(gov_db)
    dids = _seed_producers(gov_db, 10)
    _seed_signature(gov_db, "pet-test-001", dids[0])
    _seed_signature(gov_db, "pet-test-001", dids[1], signature_hex="bb" * 32)
    assert check_threshold(petition_id="pet-test-001", db_path=gov_db) is True


def test_check_threshold_false_when_zero_producers(gov_db: str) -> None:
    """No active producers → return False (no divide-by-zero)."""
    _seed_petition(gov_db)
    assert check_threshold(petition_id="pet-test-001", db_path=gov_db) is False


def test_check_threshold_ignores_inactive_producers(gov_db: str) -> None:
    """Only active producers count in the denominator."""
    _seed_petition(gov_db)
    active_dids = _seed_producers(gov_db, 5, active=1)
    _seed_producers(gov_db, 10, active=0, offset=5)  # Disjoint DIDs.
    _seed_signature(gov_db, "pet-test-001", active_dids[0])
    # 1 sig / 5 active = 0.20 → fires.
    assert check_threshold(petition_id="pet-test-001", db_path=gov_db) is True


def test_check_threshold_custom_threshold(gov_db: str) -> None:
    _seed_petition(gov_db)
    dids = _seed_producers(gov_db, 5)
    _seed_signature(gov_db, "pet-test-001", dids[0])
    # 1/5 = 0.20
    assert (
        check_threshold(petition_id="pet-test-001", db_path=gov_db, threshold=0.15)
        is True
    )
    assert (
        check_threshold(petition_id="pet-test-001", db_path=gov_db, threshold=0.25)
        is False
    )


# ---------------------------------------------------------------------------
# fire_petition
# ---------------------------------------------------------------------------


def test_fire_petition_creates_session_with_trigger(gov_db: str) -> None:
    _seed_petition(gov_db)
    session_id = fire_petition(petition_id="pet-test-001", db_path=gov_db)
    assert session_id.startswith("petition-")
    conn = sqlite3.connect(gov_db)
    row = conn.execute(
        "SELECT state, trigger FROM legislative_session WHERE session_id = ?",
        (session_id,),
    ).fetchone()
    conn.close()
    assert row == ("SESSION_INIT", "petition")


def test_fire_petition_marks_petition_fired(gov_db: str) -> None:
    _seed_petition(gov_db)
    session_id = fire_petition(petition_id="pet-test-001", db_path=gov_db)
    conn = sqlite3.connect(gov_db)
    row = conn.execute(
        "SELECT fired_at, fired_session_id FROM petition "
        "WHERE petition_id = 'pet-test-001'"
    ).fetchone()
    conn.close()
    assert row[0] is not None
    assert row[1] == session_id


def test_fire_petition_missing_petition_raises(gov_db: str) -> None:
    with pytest.raises(ValueError, match="petition pet-missing not found"):
        fire_petition(petition_id="pet-missing", db_path=gov_db)
