"""Observatory WebSocket handler — real-time event streaming."""
from __future__ import annotations

import asyncio
import json
import logging
from collections import deque
from typing import Any

from fastapi import WebSocket, WebSocketDisconnect

from oasis.observatory.event_bus import EventBus
from oasis.observatory.events import Event, EventType, serialize_event

logger = logging.getLogger(__name__)

MAX_CLIENT_QUEUE = 1000


async def websocket_events(ws: WebSocket, bus: EventBus) -> None:
    """Stream events over a WebSocket connection with optional filters.

    Query params:
        types    — comma-separated EventType values (e.g. "VOTE_CAST,TASK_ASSIGNED")
        session_id — filter by session
        agent_did  — filter by agent
    """
    await ws.accept()

    # Parse filter params from query string
    type_param = ws.query_params.get("types")
    session_id = ws.query_params.get("session_id")
    agent_did = ws.query_params.get("agent_did")

    allowed_types: set[str] | None = None
    if type_param:
        allowed_types = set(type_param.split(","))

    # Bounded queue for backpressure
    queue: deque[str] = deque(maxlen=MAX_CLIENT_QUEUE)
    event_ready = asyncio.Event()

    def _on_event(event: Event) -> None:
        """Subscriber callback — push serialised event into bounded queue."""
        queue.append(serialize_event(event))
        # Signal the send loop
        event_ready.set()

    def _event_filter(event: Event) -> bool:
        """Filter events based on query params."""
        if allowed_types is not None:
            val = event.event_type.value if isinstance(event.event_type, EventType) else event.event_type
            if val not in allowed_types:
                return False
        if session_id is not None and event.session_id != session_id:
            return False
        if agent_did is not None and event.agent_did != agent_did:
            return False
        return True

    sub_id = bus.subscribe(_on_event, _event_filter)

    try:
        while True:
            # Wait for events or client disconnect
            event_ready.clear()
            # Drain the queue
            while queue:
                msg = queue.popleft()
                await ws.send_text(msg)

            # Wait until new events arrive (with timeout for disconnect checking)
            try:
                await asyncio.wait_for(event_ready.wait(), timeout=30.0)
            except asyncio.TimeoutError:
                # Send ping to keep connection alive / detect disconnect
                try:
                    await ws.send_text('{"ping": true}')
                except Exception:
                    break
    except WebSocketDisconnect:
        pass
    except Exception:
        logger.debug("WebSocket connection closed")
    finally:
        bus.unsubscribe(sub_id)
