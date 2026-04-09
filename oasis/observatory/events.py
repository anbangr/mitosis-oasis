"""Observatory event types, dataclass, and serialization."""
from __future__ import annotations

import json
import uuid
import time
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Any


class EventType(str, Enum):
    """All observable event categories across the three branches."""

    # Session lifecycle
    SESSION_CREATED = "SESSION_CREATED"
    SESSION_STATE_CHANGED = "SESSION_STATE_CHANGED"

    # Identity
    IDENTITY_VERIFIED = "IDENTITY_VERIFIED"

    # Legislative
    PROPOSAL_SUBMITTED = "PROPOSAL_SUBMITTED"
    DELIBERATION_ROUND = "DELIBERATION_ROUND"
    VOTE_CAST = "VOTE_CAST"
    BID_SUBMITTED = "BID_SUBMITTED"
    REGULATORY_DECISION_MADE = "REGULATORY_DECISION_MADE"
    SPEC_COMPILED = "SPEC_COMPILED"
    SESSION_DEPLOYED = "SESSION_DEPLOYED"

    # Execution
    TASK_ASSIGNED = "TASK_ASSIGNED"
    TASK_COMMITTED = "TASK_COMMITTED"
    TASK_EXECUTED = "TASK_EXECUTED"
    TASK_VALIDATED = "TASK_VALIDATED"
    TASK_SETTLED = "TASK_SETTLED"

    # Adjudication
    GUARDIAN_ALERT_RAISED = "GUARDIAN_ALERT_RAISED"
    AGENT_FROZEN = "AGENT_FROZEN"
    AGENT_UNFROZEN = "AGENT_UNFROZEN"
    STAKE_SLASHED = "STAKE_SLASHED"
    REPUTATION_UPDATED = "REPUTATION_UPDATED"
    COORDINATION_FLAGGED = "COORDINATION_FLAGGED"
    TREASURY_ENTRY = "TREASURY_ENTRY"


@dataclass
class Event:
    """A single observable event."""

    event_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    event_type: EventType = EventType.SESSION_CREATED
    timestamp: float = field(default_factory=time.time)
    session_id: str | None = None
    agent_did: str | None = None
    payload: dict[str, Any] = field(default_factory=dict)
    sequence_number: int = 0


def serialize_event(event: Event) -> str:
    """Serialize an Event to a JSON string for WebSocket transmission."""
    d = asdict(event)
    # Convert EventType enum to its string value
    d["event_type"] = event.event_type.value
    return json.dumps(d)


def deserialize_event(data: str) -> Event:
    """Deserialize a JSON string back to an Event."""
    d = json.loads(data)
    d["event_type"] = EventType(d["event_type"])
    return Event(**d)
