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
"""Spec leg §5 — Frozen-evidence rule.

Once Discussion starts, the proposal's evidence snapshot is hashed and
written to ``evidence_anchor``. A second call for the same session must
be rejected (UNIQUE constraint on ``session_id`` + application-level
``ValueError``).
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from oasis.governance.endpoints import _maybe_freeze_evidence
from oasis.governance.schema import create_governance_tables


@pytest.fixture
def gov_db(tmp_path: Path) -> str:
    """Fresh governance DB with Bundle-5 schema applied."""
    db = tmp_path / "g.db"
    create_governance_tables(str(db))
    return str(db)


def _seed_session(db_path: str, session_id: str = "s-1") -> None:
    conn = sqlite3.connect(db_path)
    conn.execute(
        "INSERT INTO legislative_session (session_id, state) "
        "VALUES (?, 'SESSION_INIT')",
        (session_id,),
    )
    conn.commit()
    conn.close()


def test_t1_first_freeze_inserts_anchor_row(gov_db: str) -> None:
    """First call writes an anchor row with a SHA-256 merkle_root_hex."""
    _seed_session(gov_db, "s-1")
    _maybe_freeze_evidence(
        session_id="s-1",
        snapshot={"proposals": ["p1", "p2"], "evidence": []},
        db_path=gov_db,
    )
    conn = sqlite3.connect(gov_db)
    row = conn.execute(
        "SELECT session_id, length(merkle_root_hex) FROM evidence_anchor "
        "WHERE session_id = ?",
        ("s-1",),
    ).fetchone()
    conn.close()
    assert row == ("s-1", 64), (
        "first freeze must insert one anchor with 64-char hex digest"
    )


def test_t2_second_freeze_for_same_session_raises_value_error(gov_db: str) -> None:
    """Second call for the same session raises ValueError (spec §5)."""
    _seed_session(gov_db, "s-2")
    _maybe_freeze_evidence(
        session_id="s-2",
        snapshot={"x": 1},
        db_path=gov_db,
    )
    with pytest.raises(ValueError, match="evidence already frozen"):
        _maybe_freeze_evidence(
            session_id="s-2",
            snapshot={"x": 2},  # different snapshot — still rejected
            db_path=gov_db,
        )


def test_t3_different_sessions_can_each_freeze_independently(gov_db: str) -> None:
    """Two different sessions can each freeze without interference."""
    _seed_session(gov_db, "s-3")
    _seed_session(gov_db, "s-4")
    _maybe_freeze_evidence(
        session_id="s-3",
        snapshot={"a": 1},
        db_path=gov_db,
    )
    _maybe_freeze_evidence(
        session_id="s-4",
        snapshot={"a": 1},
        db_path=gov_db,
    )
    conn = sqlite3.connect(gov_db)
    count = conn.execute(
        "SELECT COUNT(*) FROM evidence_anchor WHERE session_id IN ('s-3', 's-4')"
    ).fetchone()[0]
    conn.close()
    assert count == 2, "both sessions must have independent anchor rows"


def test_t4_merkle_root_is_deterministic_for_same_snapshot(gov_db: str) -> None:
    """Same snapshot dict → same merkle_root_hex (sort_keys canonicalization)."""
    _seed_session(gov_db, "s-5a")
    _seed_session(gov_db, "s-5b")
    snapshot = {"b": 2, "a": 1, "c": [3, 4]}
    _maybe_freeze_evidence(
        session_id="s-5a",
        snapshot=snapshot,
        db_path=gov_db,
    )
    _maybe_freeze_evidence(
        session_id="s-5b",
        snapshot=snapshot,
        db_path=gov_db,
    )
    conn = sqlite3.connect(gov_db)
    roots = conn.execute(
        "SELECT merkle_root_hex FROM evidence_anchor "
        "WHERE session_id IN ('s-5a', 's-5b')"
    ).fetchall()
    conn.close()
    assert len({r[0] for r in roots}) == 1, (
        "same snapshot dict must produce same merkle root (canonical JSON)"
    )
