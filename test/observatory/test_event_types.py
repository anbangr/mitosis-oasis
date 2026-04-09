"""Tests for event types, serialization, and sequence numbering."""
from __future__ import annotations

import json

from oasis.observatory.events import Event, EventType, serialize_event, deserialize_event
from oasis.observatory.event_bus import EventBus


def test_all_event_types_defined():
    """All 22 expected event types are defined in the enum."""
    expected = {
        "SESSION_CREATED", "SESSION_STATE_CHANGED", "IDENTITY_VERIFIED",
        "PROPOSAL_SUBMITTED", "DELIBERATION_ROUND", "VOTE_CAST",
        "BID_SUBMITTED", "REGULATORY_DECISION_MADE", "SPEC_COMPILED",
        "SESSION_DEPLOYED", "TASK_ASSIGNED", "TASK_COMMITTED",
        "TASK_EXECUTED", "TASK_VALIDATED", "TASK_SETTLED",
        "GUARDIAN_ALERT_RAISED", "AGENT_FROZEN", "AGENT_UNFROZEN",
        "STAKE_SLASHED", "REPUTATION_UPDATED", "COORDINATION_FLAGGED",
        "TREASURY_ENTRY",
    }
    actual = {e.value for e in EventType}
    assert expected == actual


def test_serialization_round_trip():
    """An Event survives JSON serialization and deserialization."""
    event = Event(
        event_type=EventType.VOTE_CAST,
        session_id="sess-001",
        agent_did="did:test:1",
        payload={"choice": [1, 2, 3]},
    )
    json_str = serialize_event(event)
    parsed = json.loads(json_str)
    assert parsed["event_type"] == "VOTE_CAST"
    assert parsed["session_id"] == "sess-001"
    assert parsed["payload"]["choice"] == [1, 2, 3]

    # Full round-trip
    restored = deserialize_event(json_str)
    assert restored.event_type == EventType.VOTE_CAST
    assert restored.session_id == event.session_id
    assert restored.payload == event.payload


def test_sequence_number_monotonic(event_bus: EventBus):
    """Published events get strictly monotonic sequence numbers."""
    events = []
    for i in range(10):
        e = Event(event_type=EventType.TASK_ASSIGNED, payload={"i": i})
        published = event_bus.publish(e)
        events.append(published)

    seq_nums = [e.sequence_number for e in events]
    assert seq_nums == sorted(seq_nums)
    assert len(set(seq_nums)) == 10  # all unique
    assert seq_nums[0] >= 1
    for i in range(1, len(seq_nums)):
        assert seq_nums[i] == seq_nums[i - 1] + 1
