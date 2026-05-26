"""Subscribe to oasis EventBus during a call and collect emitted events."""

from pathlib import Path

import pytest

from oasis.observatory.event_bus import EventBus
from oasis.observatory.events import Event, EventType
from test.conformance.adapter.event_capture import EventCollector


@pytest.fixture
def fresh_bus(tmp_path: Path):
    EventBus.reset()
    db = tmp_path / "obs.db"
    bus = EventBus.get_instance(db_path=db)
    yield bus
    EventBus.reset()


def test_collector_records_events_emitted_inside_with_block(fresh_bus):
    with EventCollector() as collector:
        fresh_bus.publish(
            Event(
                event_type=EventType.PROPOSAL_SUBMITTED, payload={"proposal_id": "p1"}
            )
        )
    assert len(collector.events) == 1
    assert collector.events[0].event_type == EventType.PROPOSAL_SUBMITTED
    assert collector.events[0].payload == {"proposal_id": "p1"}


def test_collector_ignores_events_emitted_before_or_after_block(fresh_bus):
    fresh_bus.publish(Event(event_type=EventType.SESSION_CREATED))
    with EventCollector() as collector:
        fresh_bus.publish(Event(event_type=EventType.VOTE_CAST, payload={"v": "1"}))
    fresh_bus.publish(Event(event_type=EventType.SESSION_CREATED))
    assert len(collector.events) == 1
    assert collector.events[0].event_type == EventType.VOTE_CAST


def test_collector_preserves_publish_order(fresh_bus):
    types = [EventType.PROPOSAL_SUBMITTED, EventType.VOTE_CAST, EventType.SPEC_COMPILED]
    with EventCollector() as collector:
        for t in types:
            fresh_bus.publish(Event(event_type=t))
    assert [e.event_type for e in collector.events] == types


def test_collector_raises_clear_error_when_bus_not_initialised():
    """EventCollector must raise RuntimeError with a seed-hint message when the
    EventBus singleton has not yet been initialised (no db_path provided)."""
    EventBus.reset()
    with pytest.raises(RuntimeError, match="EventCollector requires"):
        with EventCollector():
            pass  # pragma: no cover
