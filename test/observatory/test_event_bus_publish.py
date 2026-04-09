"""Tests for EventBus publish, subscriber notification, and filtering."""
from __future__ import annotations

import sqlite3

from oasis.observatory.event_bus import EventBus
from oasis.observatory.events import Event, EventType


def test_event_published_and_persisted(event_bus: EventBus, observatory_db):
    """Published event is persisted to the event_log table."""
    event = Event(
        event_type=EventType.SESSION_CREATED,
        session_id="sess-pub-001",
        payload={"name": "test"},
    )
    published = event_bus.publish(event)

    conn = sqlite3.connect(str(observatory_db))
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        "SELECT * FROM event_log WHERE event_id = ?", (published.event_id,)
    ).fetchone()
    conn.close()

    assert row is not None
    assert row["event_type"] == "SESSION_CREATED"
    assert row["session_id"] == "sess-pub-001"
    assert row["sequence_number"] == published.sequence_number


def test_subscriber_notified(event_bus: EventBus):
    """A subscriber callback is invoked when an event is published."""
    received = []
    event_bus.subscribe(lambda e: received.append(e))

    event = Event(event_type=EventType.VOTE_CAST, session_id="sess-sub-001")
    event_bus.publish(event)

    assert len(received) == 1
    assert received[0].event_type == EventType.VOTE_CAST


def test_subscriber_filter_applied(event_bus: EventBus):
    """A subscriber with a filter only receives matching events."""
    received = []

    def vote_filter(e: Event) -> bool:
        return e.event_type == EventType.VOTE_CAST

    event_bus.subscribe(lambda e: received.append(e), filter=vote_filter)

    event_bus.publish(Event(event_type=EventType.SESSION_CREATED))
    event_bus.publish(Event(event_type=EventType.VOTE_CAST))
    event_bus.publish(Event(event_type=EventType.TASK_ASSIGNED))

    assert len(received) == 1
    assert received[0].event_type == EventType.VOTE_CAST
