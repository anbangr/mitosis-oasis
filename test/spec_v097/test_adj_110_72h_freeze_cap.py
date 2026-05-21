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
"""ADJ-110 — 72-hour freeze auto-lift cap.

This test verifies that ``sweep_expired_freezes`` auto-lifts freezes older
than 72h (``max_freeze_duration_ms = 259_200_000``) while respecting
``manual_extension`` and idempotency.  It MUST be red before the
implementation is written (TDD invariant).
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from oasis.adjudication.schema import create_adjudication_tables
from oasis.adjudication.freeze_sweeper import sweep_expired_freezes


MAX_FREEZE_DURATION_MS = 259_200_000


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------


def _seed_agent(db_path: Path, agent_did: str) -> None:
    """Seed a single agent so adjudication_decision FK does not fail."""
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute(
        "INSERT OR IGNORE INTO agent_registry "
        "(agent_did, agent_type, display_name) VALUES (?, 'producer', ?)",
        (agent_did, agent_did),
    )
    conn.commit()
    conn.close()


def _insert_freeze(
    db_path: Path,
    *,
    agent_did: str,
    frozen_at_offset: str,
    manual_extension: int = 0,
    decision_id: str | None = None,
) -> str:
    """Insert a freeze decision with a specific frozen_at offset.

    ``frozen_at_offset`` is an SQLite datetime expression such as
    ``'-73 hours'`` or ``'-71 hours'``.
    """
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA foreign_keys = ON")
    _decision_id = decision_id or f"freeze-{agent_did.replace(':', '-')}-001"
    conn.execute(
        "INSERT INTO adjudication_decision "
        "(decision_id, agent_did, decision_type, severity, reason, "
        "layer1_result, frozen_at, manual_extension) "
        "VALUES (?, ?, 'freeze', 'CRITICAL', 'frozen for testing', 'frozen', "
        "datetime('now', ?), ?)",
        (_decision_id, agent_did, frozen_at_offset, manual_extension),
    )
    conn.commit()
    conn.close()
    return _decision_id


@pytest.fixture()
def adj_db(tmp_path: Path) -> Path:
    """Fresh adjudication DB with schema and a seeded agent."""
    db_path = tmp_path / "adj.db"
    create_adjudication_tables(db_path)
    _seed_agent(db_path, "did:key:zAgent1")
    return db_path


# ---------------------------------------------------------------------------
# T1 — Freeze older than 72h is auto-lifted
# ---------------------------------------------------------------------------


def test_freeze_older_than_72h_auto_lifted(adj_db: Path) -> None:
    """T1: One freeze at now-73h, no extension → unfreeze inserted."""
    _insert_freeze(adj_db, agent_did="did:key:zAgent1", frozen_at_offset="-73 hours")

    count = sweep_expired_freezes(
        db_path=str(adj_db),
        max_duration_ms=MAX_FREEZE_DURATION_MS,
    )

    assert count == 1

    conn = sqlite3.connect(str(adj_db))
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT decision_type, reason, layer1_result FROM adjudication_decision "
        "WHERE agent_did = ? ORDER BY created_at DESC",
        ("did:key:zAgent1",),
    ).fetchall()
    conn.close()

    assert len(rows) == 2  # original freeze + auto-lift unfreeze
    assert rows[0]["decision_type"] == "unfreeze"
    assert "auto-lifted" in rows[0]["reason"]


# ---------------------------------------------------------------------------
# T2 — Freeze younger than 72h is not lifted
# ---------------------------------------------------------------------------


def test_freeze_younger_than_72h_not_lifted(adj_db: Path) -> None:
    """T2: One freeze at now-71h → no unfreeze inserted."""
    _insert_freeze(adj_db, agent_did="did:key:zAgent1", frozen_at_offset="-71 hours")

    count = sweep_expired_freezes(
        db_path=str(adj_db),
        max_duration_ms=MAX_FREEZE_DURATION_MS,
    )

    assert count == 0

    conn = sqlite3.connect(str(adj_db))
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT decision_type FROM adjudication_decision WHERE agent_did = ?",
        ("did:key:zAgent1",),
    ).fetchall()
    conn.close()

    assert len(rows) == 1
    assert rows[0]["decision_type"] == "freeze"


# ---------------------------------------------------------------------------
# T3 — manual_extension=1 blocks auto-lift
# ---------------------------------------------------------------------------


def test_manual_extension_blocks_auto_lift(adj_db: Path) -> None:
    """T3: Freeze at now-100h with manual_extension=1 → no unfreeze inserted."""
    _insert_freeze(
        adj_db,
        agent_did="did:key:zAgent1",
        frozen_at_offset="-100 hours",
        manual_extension=1,
    )

    count = sweep_expired_freezes(
        db_path=str(adj_db),
        max_duration_ms=MAX_FREEZE_DURATION_MS,
    )

    assert count == 0

    conn = sqlite3.connect(str(adj_db))
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT decision_type FROM adjudication_decision WHERE agent_did = ?",
        ("did:key:zAgent1",),
    ).fetchall()
    conn.close()

    assert len(rows) == 1
    assert rows[0]["decision_type"] == "freeze"
