"""Tests for WebSocket event streaming."""
from __future__ import annotations

import asyncio
import json
import threading

import pytest
from fastapi import FastAPI, WebSocket
from fastapi.testclient import TestClient

from oasis.observatory.event_bus import EventBus
from oasis.observatory.events import Event, EventType
from oasis.observatory.websocket import websocket_events


def _make_app(bus: EventBus) -> FastAPI:
    """Create a minimal FastAPI app with the WS endpoint for testing."""
    app = FastAPI()

    @app.websocket("/ws/events")
    async def ws_endpoint(ws: WebSocket):
        await websocket_events(ws, bus)

    return app


def test_events_streamed_to_client(event_bus: EventBus):
    """Events published to the bus are streamed to a connected WebSocket client."""
    app = _make_app(event_bus)

    with TestClient(app) as client:
        with client.websocket_connect("/ws/events") as ws:
            # Publish an event (from another thread to simulate async)
            event = Event(
                event_type=EventType.VOTE_CAST,
                session_id="ws-sess-001",
                payload={"rank": [1, 2]},
            )
            event_bus.publish(event)

            # Give the WS loop time to drain
            data = ws.receive_json(mode="text")
            assert data["event_type"] == "VOTE_CAST"
            assert data["session_id"] == "ws-sess-001"


def test_filter_params_work(event_bus: EventBus):
    """WebSocket filter query params restrict which events are streamed."""
    app = _make_app(event_bus)

    with TestClient(app) as client:
        with client.websocket_connect("/ws/events?types=VOTE_CAST") as ws:
            # This event should NOT be sent (wrong type)
            event_bus.publish(Event(event_type=EventType.SESSION_CREATED))
            # This event SHOULD be sent
            event_bus.publish(Event(event_type=EventType.VOTE_CAST, payload={"ok": True}))

            data = ws.receive_json(mode="text")
            assert data["event_type"] == "VOTE_CAST"


def test_disconnect_cleanup(event_bus: EventBus):
    """Subscriber is removed when WebSocket disconnects."""
    app = _make_app(event_bus)

    initial_subs = len(event_bus._subscribers)

    with TestClient(app) as client:
        with client.websocket_connect("/ws/events") as ws:
            assert len(event_bus._subscribers) == initial_subs + 1

    # After disconnect, subscriber should be cleaned up
    # Give cleanup a moment
    import time
    time.sleep(0.1)
    assert len(event_bus._subscribers) == initial_subs
