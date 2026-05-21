"""Freeze sweeper unit tests (Feature 4, Phase 1).

These tests verify the ``sweep_expired_freezes`` helper in
``oasis.adjudication.freeze_sweeper``.  They MUST be red before the
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
    """Insert a freeze decision with a specific frozen_at offset."""
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


def _insert_unfreeze(
    db_path: Path,
    *,
    agent_did: str,
    created_at_offset: str,
    decision_id: str | None = None,
) -> str:
    """Insert an unfreeze decision with a specific created_at offset."""
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA foreign_keys = ON")
    _decision_id = decision_id or f"unfreeze-{agent_did.replace(':', '-')}-001"
    conn.execute(
        "INSERT INTO adjudication_decision "
        "(decision_id, agent_did, decision_type, severity, reason, "
        "layer1_result, created_at) "
        "VALUES (?, ?, 'unfreeze', 'INFO', 'manual unfreeze', 'unfrozen', "
        "datetime('now', ?))",
        (_decision_id, agent_did, created_at_offset),
    )
    conn.commit()
    conn.close()
    return _decision_id


@pytest.fixture()
def adj_db(tmp_path: Path) -> Path:
    """Fresh adjudication DB with schema and seeded agents."""
    db_path = tmp_path / "adj.db"
    create_adjudication_tables(db_path)
    _seed_agent(db_path, "did:key:zAgent1")
    _seed_agent(db_path, "did:key:zAgent2")
    _seed_agent(db_path, "did:key:zAgent3")
    return db_path


# ---------------------------------------------------------------------------
# T4 — Idempotency: sweep twice does not double-lift
# ---------------------------------------------------------------------------


def test_sweep_twice_does_not_double_lift(adj_db: Path) -> None:
    """T4: Sweeping twice on the same expired freeze inserts exactly 1 unfreeze."""
    _insert_freeze(adj_db, agent_did="did:key:zAgent1", frozen_at_offset="-75 hours")

    count_first = sweep_expired_freezes(
        db_path=str(adj_db),
        max_duration_ms=MAX_FREEZE_DURATION_MS,
    )
    count_second = sweep_expired_freezes(
        db_path=str(adj_db),
        max_duration_ms=MAX_FREEZE_DURATION_MS,
    )

    assert count_first == 1
    assert count_second == 0

    conn = sqlite3.connect(str(adj_db))
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT decision_type FROM adjudication_decision WHERE agent_did = ?",
        ("did:key:zAgent1",),
    ).fetchall()
    conn.close()

    assert len(rows) == 2  # freeze + exactly one unfreeze
    unfreeze_rows = [r for r in rows if r["decision_type"] == "unfreeze"]
    assert len(unfreeze_rows) == 1


# ---------------------------------------------------------------------------
# Edge case — exactly 72h-old freeze is lifted (boundary, <=)
# ---------------------------------------------------------------------------


def test_exactly_72h_boundary_is_lifted(adj_db: Path) -> None:
    """A freeze at exactly now-72h matches the <= boundary and is lifted."""
    _insert_freeze(adj_db, agent_did="did:key:zAgent1", frozen_at_offset="-72 hours")

    count = sweep_expired_freezes(
        db_path=str(adj_db),
        max_duration_ms=MAX_FREEZE_DURATION_MS,
    )

    assert count == 1

    conn = sqlite3.connect(str(adj_db))
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT decision_type FROM adjudication_decision WHERE agent_did = ?",
        ("did:key:zAgent1",),
    ).fetchall()
    conn.close()

    assert len(rows) == 2
    assert rows[-1]["decision_type"] == "unfreeze"


# ---------------------------------------------------------------------------
# Edge case — multiple expired freezes for same agent
# ---------------------------------------------------------------------------


def test_multiple_expired_freezes_same_agent(adj_db: Path) -> None:
    """Two expired freezes for the same agent → two unfreeze rows inserted."""
    _insert_freeze(
        adj_db,
        agent_did="did:key:zAgent1",
        frozen_at_offset="-80 hours",
        decision_id="freeze-001",
    )
    _insert_freeze(
        adj_db,
        agent_did="did:key:zAgent1",
        frozen_at_offset="-76 hours",
        decision_id="freeze-002",
    )

    count = sweep_expired_freezes(
        db_path=str(adj_db),
        max_duration_ms=MAX_FREEZE_DURATION_MS,
    )

    assert count == 2

    conn = sqlite3.connect(str(adj_db))
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT decision_type FROM adjudication_decision WHERE agent_did = ?",
        ("did:key:zAgent1",),
    ).fetchall()
    conn.close()

    assert len(rows) == 4  # 2 freezes + 2 unfreezes
    unfreeze_rows = [r for r in rows if r["decision_type"] == "unfreeze"]
    assert len(unfreeze_rows) == 2


# ---------------------------------------------------------------------------
# Edge case — manually unfrozen earlier then re-frozen
# ---------------------------------------------------------------------------


def test_manually_unfrozen_then_refrozen_only_latest_considered(adj_db: Path) -> None:
    """An agent manually unfrozen then re-frozen: only the latest freeze is lifted."""
    # Old freeze (expired) followed by manual unfreeze
    _insert_freeze(
        adj_db,
        agent_did="did:key:zAgent1",
        frozen_at_offset="-100 hours",
        decision_id="freeze-old",
    )
    _insert_unfreeze(
        adj_db,
        agent_did="did:key:zAgent1",
        created_at_offset="-90 hours",
        decision_id="unfreeze-old",
    )
    # Newer freeze (also expired) — this is the one that should be lifted
    _insert_freeze(
        adj_db,
        agent_did="did:key:zAgent1",
        frozen_at_offset="-80 hours",
        decision_id="freeze-new",
    )

    count = sweep_expired_freezes(
        db_path=str(adj_db),
        max_duration_ms=MAX_FREEZE_DURATION_MS,
    )

    assert count == 1

    conn = sqlite3.connect(str(adj_db))
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT decision_id, decision_type FROM adjudication_decision "
        "WHERE agent_did = ? ORDER BY created_at DESC",
        ("did:key:zAgent1",),
    ).fetchall()
    conn.close()

    # Should have: old freeze, old unfreeze, new freeze, new auto-unfreeze
    assert len(rows) == 4
    unfreeze_rows = [r for r in rows if r["decision_type"] == "unfreeze"]
    assert len(unfreeze_rows) == 2


# ---------------------------------------------------------------------------
# Edge case — return value contract
# ---------------------------------------------------------------------------


def test_return_value_is_count_inserted(adj_db: Path) -> None:
    """The return value equals the number of unfreeze rows inserted in this call."""
    _insert_freeze(adj_db, agent_did="did:key:zAgent1", frozen_at_offset="-73 hours")
    _insert_freeze(adj_db, agent_did="did:key:zAgent2", frozen_at_offset="-74 hours")
    _insert_freeze(adj_db, agent_did="did:key:zAgent3", frozen_at_offset="-71 hours")

    count = sweep_expired_freezes(
        db_path=str(adj_db),
        max_duration_ms=MAX_FREEZE_DURATION_MS,
    )

    assert count == 2


# ---------------------------------------------------------------------------
# Edge case — expired freeze with existing later unfreeze is ignored
# ---------------------------------------------------------------------------


def test_expired_freeze_with_later_unfreeze_ignored(adj_db: Path) -> None:
    """An expired freeze that already has a later unfreeze is not lifted again."""
    _insert_freeze(
        adj_db,
        agent_did="did:key:zAgent1",
        frozen_at_offset="-80 hours",
        decision_id="freeze-001",
    )
    _insert_unfreeze(
        adj_db,
        agent_did="did:key:zAgent1",
        created_at_offset="-10 hours",
        decision_id="unfreeze-001",
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

    assert len(rows) == 2  # no new rows added
