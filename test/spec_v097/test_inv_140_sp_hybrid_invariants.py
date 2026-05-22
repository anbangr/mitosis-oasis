"""Spec exec §9.2-9.3: SP-1h–SP-4h hybrid mode invariants.

Damage bound N_unaudited ≤ r × τ_anchor (events per sec × checkpoint interval).
At each τ_anchor boundary, publish_anchor(batch_max_size=r×τ_anchor) must
leave zero unanchored events provided the ingress rate has not exceeded r.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from oasis.adjudication.anchor_publisher import publish_anchor
from oasis.observatory.schema import create_observatory_tables


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def obs_db(tmp_path: Path) -> str:
    p = tmp_path / "obs.db"
    create_observatory_tables(str(p))
    return str(p)


@pytest.fixture
def _seed_events(obs_db: str) -> None:
    """Helper fixture: returns a closure that seeds N events."""

    def _inner(n: int, start_seq: int = 1) -> None:
        conn = sqlite3.connect(obs_db)
        for i in range(n):
            conn.execute(
                "INSERT INTO event_log "
                "(event_id, event_type, timestamp, payload, sequence_number) "
                "VALUES (?, 'TEST', ?, '{}', ?)",
                (f"e{i}", float(i) / 100.0, start_seq + i),
            )
        conn.commit()
        conn.close()

    return _inner


# ---------------------------------------------------------------------------
# T1 — Damage bound satisfied
# ---------------------------------------------------------------------------


def test_unanchored_window_bounded_by_tau_anchor(obs_db: str, _seed_events) -> None:
    """At rate r=100 ev/sec and τ_anchor=10s, the unaudited window
    must contain at most 1000 events."""
    r = 100
    tau_anchor = 10
    batch_max_size = r * tau_anchor  # 1000

    _seed_events(batch_max_size)

    anchor = publish_anchor(db_path=obs_db, batch_max_size=batch_max_size)
    assert anchor is not None
    assert anchor["event_count"] == batch_max_size

    conn = sqlite3.connect(obs_db)
    remaining_unanchored = conn.execute(
        "SELECT COUNT(*) FROM event_log WHERE anchor_id IS NULL"
    ).fetchone()[0]
    conn.close()

    assert remaining_unanchored == 0, (
        f"hybrid-mode damage bound violated: {remaining_unanchored} "
        f"events unanchored after τ_anchor interval"
    )


# ---------------------------------------------------------------------------
# T2 — Rate-interval product equals batch capacity
# ---------------------------------------------------------------------------


def test_rate_interval_product_equals_batch_capacity(obs_db: str, _seed_events) -> None:
    """Rate r=100 and τ_anchor=10 produce a batch capacity of 1000 events."""
    r = 100
    tau_anchor = 10
    expected_capacity = r * tau_anchor

    _seed_events(expected_capacity)

    anchor = publish_anchor(db_path=obs_db, batch_max_size=expected_capacity)
    assert anchor is not None
    assert anchor["event_count"] == expected_capacity
    assert anchor["batch_start_seq"] == 1
    assert anchor["batch_end_seq"] == expected_capacity


# ---------------------------------------------------------------------------
# T3 — Empty window
# ---------------------------------------------------------------------------


def test_empty_window_returns_none(obs_db: str) -> None:
    """Zero events generated → publish_anchor returns None."""
    result = publish_anchor(db_path=obs_db, batch_max_size=1000)
    assert result is None


# ---------------------------------------------------------------------------
# Edge — Batch size smaller than r × τ_anchor leaves events unanchored
# ---------------------------------------------------------------------------


def test_batch_size_smaller_than_rate_tau_leaves_events_unanchored(
    obs_db: str, _seed_events
) -> None:
    """If batch_max_size < r × τ_anchor, the damage bound is exceeded
    and events remain unanchored."""
    r = 100
    tau_anchor = 10
    batch_max_size = 500  # smaller than r × τ_anchor = 1000

    _seed_events(r * tau_anchor)  # 1000 events

    anchor = publish_anchor(db_path=obs_db, batch_max_size=batch_max_size)
    assert anchor is not None
    assert anchor["event_count"] == batch_max_size

    conn = sqlite3.connect(obs_db)
    remaining = conn.execute(
        "SELECT COUNT(*) FROM event_log WHERE anchor_id IS NULL"
    ).fetchone()[0]
    conn.close()

    assert remaining == 500, (
        f"Expected 500 unanchored events when batch_max_size (500) < "
        f"r × τ_anchor (1000), got {remaining}"
    )


# ---------------------------------------------------------------------------
# Edge — Rate r = 0 produces no events and no anchor
# ---------------------------------------------------------------------------


def test_zero_rate_produces_no_events_and_no_anchor(obs_db: str) -> None:
    """At rate r=0, no events are generated and publish_anchor returns None."""
    result = publish_anchor(db_path=obs_db, batch_max_size=1000)
    assert result is None

    conn = sqlite3.connect(obs_db)
    total_events = conn.execute("SELECT COUNT(*) FROM event_log").fetchone()[0]
    conn.close()

    assert total_events == 0


# ---------------------------------------------------------------------------
# Edge — Very large τ_anchor with small r still anchors correctly
# ---------------------------------------------------------------------------


def test_large_tau_small_rate_anchors_correctly(obs_db: str, _seed_events) -> None:
    """τ_anchor=3600s and r=1 ev/sec → batch_max_size=3600.
    All 3600 events must be anchored in a single call."""
    r = 1
    tau_anchor = 3600
    batch_max_size = r * tau_anchor  # 3600

    _seed_events(batch_max_size)

    anchor = publish_anchor(db_path=obs_db, batch_max_size=batch_max_size)
    assert anchor is not None
    assert anchor["event_count"] == batch_max_size

    conn = sqlite3.connect(obs_db)
    remaining = conn.execute(
        "SELECT COUNT(*) FROM event_log WHERE anchor_id IS NULL"
    ).fetchone()[0]
    conn.close()

    assert remaining == 0


# ---------------------------------------------------------------------------
# Additional — Damage bound holds across multiple τ_anchor intervals
# ---------------------------------------------------------------------------


def test_damage_bound_holds_across_multiple_intervals(
    obs_db: str, _seed_events
) -> None:
    """Simulate two consecutive intervals: 1000 events in first window,
    500 in second. After anchoring each window, zero unanchored remain."""
    r = 100
    tau_anchor = 10
    batch_max_size = r * tau_anchor

    # First window: 1000 events
    _seed_events(1000, start_seq=1)
    anchor1 = publish_anchor(db_path=obs_db, batch_max_size=batch_max_size)
    assert anchor1["event_count"] == 1000

    # Second window: 500 events
    conn = sqlite3.connect(obs_db)
    for i in range(500):
        conn.execute(
            "INSERT INTO event_log "
            "(event_id, event_type, timestamp, payload, sequence_number) "
            "VALUES (?, 'TEST', ?, '{}', ?)",
            (f"w2_e{i}", float(1000 + i) / 100.0, 1001 + i),
        )
    conn.commit()
    conn.close()

    anchor2 = publish_anchor(db_path=obs_db, batch_max_size=batch_max_size)
    assert anchor2 is not None
    assert anchor2["event_count"] == 500

    conn = sqlite3.connect(obs_db)
    remaining = conn.execute(
        "SELECT COUNT(*) FROM event_log WHERE anchor_id IS NULL"
    ).fetchone()[0]
    conn.close()

    assert remaining == 0, f"Expected 0 unanchored after two intervals, got {remaining}"


# ---------------------------------------------------------------------------
# Additional — Burst within bound is fully anchored
# ---------------------------------------------------------------------------


def test_burst_at_exact_damage_bound_is_fully_anchored(
    obs_db: str, _seed_events
) -> None:
    """A burst of exactly r × τ_anchor events must be completely anchored."""
    r = 100
    tau_anchor = 10
    batch_max_size = r * tau_anchor

    _seed_events(batch_max_size)

    anchor = publish_anchor(db_path=obs_db, batch_max_size=batch_max_size)
    assert anchor is not None
    assert anchor["event_count"] == batch_max_size
    assert anchor["batch_start_seq"] == 1
    assert anchor["batch_end_seq"] == batch_max_size

    conn = sqlite3.connect(obs_db)
    remaining = conn.execute(
        "SELECT COUNT(*) FROM event_log WHERE anchor_id IS NULL"
    ).fetchone()[0]
    conn.close()

    assert remaining == 0
