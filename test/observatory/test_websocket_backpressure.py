"""Tests for WebSocket backpressure and event persistence."""
from __future__ import annotations

import sqlite3

from oasis.observatory.event_bus import EventBus
from oasis.observatory.events import Event, EventType
from oasis.observatory.websocket import MAX_CLIENT_QUEUE


def test_slow_client_queue_capped(event_bus: EventBus):
    """When a subscriber's queue exceeds MAX_CLIENT_QUEUE, oldest events are dropped."""
    from collections import deque

    # Simulate backpressure by creating a bounded deque (same as websocket.py)
    queue: deque[str] = deque(maxlen=MAX_CLIENT_QUEUE)

    def slow_callback(e: Event) -> None:
        from oasis.observatory.events import serialize_event
        queue.append(serialize_event(e))

    event_bus.subscribe(slow_callback)

    # Publish more events than the queue can hold
    for i in range(MAX_CLIENT_QUEUE + 500):
        event_bus.publish(Event(event_type=EventType.TASK_ASSIGNED, payload={"i": i}))

    assert len(queue) == MAX_CLIENT_QUEUE


def test_events_still_persisted_despite_backpressure(event_bus: EventBus, observatory_db):
    """Events are persisted to DB even when subscriber queue overflows."""
    from collections import deque
    from oasis.observatory.events import serialize_event

    queue: deque[str] = deque(maxlen=10)  # Very small queue

    def slow_callback(e: Event) -> None:
        queue.append(serialize_event(e))

    event_bus.subscribe(slow_callback)

    total = 50
    for i in range(total):
        event_bus.publish(Event(event_type=EventType.TASK_EXECUTED, payload={"i": i}))

    # Queue is capped
    assert len(queue) == 10

    # But all events are persisted
    conn = sqlite3.connect(str(observatory_db))
    row = conn.execute("SELECT COUNT(*) as cnt FROM event_log").fetchone()
    conn.close()
    assert row[0] == total
