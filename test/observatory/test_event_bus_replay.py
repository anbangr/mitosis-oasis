"""Tests for EventBus replay functionality."""
from __future__ import annotations

from oasis.observatory.event_bus import EventBus
from oasis.observatory.events import Event, EventType


def test_replay_from_sequence(event_bus: EventBus):
    """Replay returns events after the given sequence number."""
    for i in range(5):
        event_bus.publish(Event(event_type=EventType.TASK_ASSIGNED, payload={"i": i}))

    # Replay from sequence 3 — should get events 4 and 5
    events = event_bus.replay(since_sequence=3)
    assert len(events) == 2
    assert events[0].sequence_number == 4
    assert events[1].sequence_number == 5


def test_replay_with_type_filter(event_bus: EventBus):
    """Replay filters by event type."""
    event_bus.publish(Event(event_type=EventType.SESSION_CREATED))
    event_bus.publish(Event(event_type=EventType.VOTE_CAST))
    event_bus.publish(Event(event_type=EventType.SESSION_CREATED))
    event_bus.publish(Event(event_type=EventType.TASK_ASSIGNED))

    events = event_bus.replay(event_types=[EventType.SESSION_CREATED])
    assert len(events) == 2
    assert all(e.event_type == EventType.SESSION_CREATED for e in events)


def test_replay_with_session_filter(event_bus: EventBus):
    """Replay filters by session_id."""
    event_bus.publish(Event(event_type=EventType.VOTE_CAST, session_id="sess-A"))
    event_bus.publish(Event(event_type=EventType.VOTE_CAST, session_id="sess-B"))
    event_bus.publish(Event(event_type=EventType.VOTE_CAST, session_id="sess-A"))

    events = event_bus.replay(session_id="sess-A")
    assert len(events) == 2
    assert all(e.session_id == "sess-A" for e in events)
