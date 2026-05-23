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
"""Spec leg §2.2 — petition trigger fires when ≥petition_threshold signatures land."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from oasis.governance.schema import create_governance_tables
from oasis.governance.scheduler.petition_trigger import (
    accumulate_signature,
    check_threshold,
    fire_petition,
)


@pytest.fixture
def gov_db(tmp_path: Path) -> str:
    db = tmp_path / "g.db"
    create_governance_tables(str(db))
    return str(db)


def _seed_petition(db_path: str, petition_id: str = "pet-001") -> None:
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            "INSERT INTO petition (petition_id, title, rationale, proposed_mission) "
            "VALUES (?, ?, ?, ?)",
            (petition_id, "Title", "Why", "Mission"),
        )
        conn.commit()
    finally:
        conn.close()


def _seed_producers(db_path: str, n: int) -> list[str]:
    conn = sqlite3.connect(db_path)
    try:
        dids: list[str] = []
        for i in range(n):
            did = f"did:key:zProducer{i}"
            dids.append(did)
            conn.execute(
                "INSERT INTO agent_registry "
                "(agent_did, agent_type, display_name, active) "
                "VALUES (?, 'producer', ?, 1)",
                (did, f"Producer {i}"),
            )
        conn.commit()
        return dids
    finally:
        conn.close()


def test_t1_threshold_not_reached(gov_db: str) -> None:
    """T1: 10 producers, 1 signature (10%) → threshold NOT reached."""
    _seed_petition(gov_db)
    dids = _seed_producers(gov_db, 10)
    accumulate_signature(
        petition_id="pet-001",
        signer_did=dids[0],
        signature_hex="aa" * 32,
        db_path=gov_db,
    )
    assert check_threshold(petition_id="pet-001", db_path=gov_db) is False


def test_t2_threshold_reached(gov_db: str) -> None:
    """T2: 10 producers, 2 signatures (20%) → threshold reached."""
    _seed_petition(gov_db)
    dids = _seed_producers(gov_db, 10)
    accumulate_signature(
        petition_id="pet-001",
        signer_did=dids[0],
        signature_hex="aa" * 32,
        db_path=gov_db,
    )
    accumulate_signature(
        petition_id="pet-001",
        signer_did=dids[1],
        signature_hex="bb" * 32,
        db_path=gov_db,
    )
    assert check_threshold(petition_id="pet-001", db_path=gov_db) is True


def test_t3_duplicate_signer_rejected(gov_db: str) -> None:
    """T3: A given producer can only sign once (UNIQUE constraint)."""
    _seed_petition(gov_db)
    dids = _seed_producers(gov_db, 10)
    accumulate_signature(
        petition_id="pet-001",
        signer_did=dids[0],
        signature_hex="aa" * 32,
        db_path=gov_db,
    )
    with pytest.raises(sqlite3.IntegrityError):
        accumulate_signature(
            petition_id="pet-001",
            signer_did=dids[0],
            signature_hex="cc" * 32,
            db_path=gov_db,
        )


def test_t4_firing_creates_session_and_marks_petition(gov_db: str) -> None:
    """T4: fire_petition creates legislative_session and marks petition fired."""
    _seed_petition(gov_db)
    session_id = fire_petition(petition_id="pet-001", db_path=gov_db)
    assert session_id.startswith("petition-")

    conn = sqlite3.connect(gov_db)
    try:
        sess = conn.execute(
            "SELECT state, trigger FROM legislative_session WHERE session_id = ?",
            (session_id,),
        ).fetchone()
        pet = conn.execute(
            "SELECT fired_at, fired_session_id FROM petition "
            "WHERE petition_id = 'pet-001'"
        ).fetchone()
    finally:
        conn.close()

    assert sess == ("SESSION_INIT", "petition")
    assert pet[0] is not None
    assert pet[1] == session_id
