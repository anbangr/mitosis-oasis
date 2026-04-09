"""Observatory event bus — singleton publish/subscribe with SQLite persistence."""
from __future__ import annotations

import json
import sqlite3
import threading
from pathlib import Path
from typing import Any, Callable, Union

from oasis.observatory.events import Event, EventType, serialize_event
from oasis.observatory.schema import create_observatory_tables


class EventBus:
    """Thread-safe event bus with SQLite persistence and subscriber notification.

    Singleton: use ``EventBus.get_instance(db_path)`` or construct directly.
    """

    _instance: EventBus | None = None
    _lock = threading.Lock()

    def __init__(self, db_path: Union[str, Path]) -> None:
        self._db_path = str(db_path)
        self._sequence = 0
        self._seq_lock = threading.Lock()
        self._subscribers: dict[str, tuple[Callable[[Event], Any], Callable[[Event], bool] | None]] = {}
        self._sub_id_counter = 0
        self._sub_lock = threading.Lock()

        # Ensure tables exist
        create_observatory_tables(self._db_path)

        # Resume sequence counter from DB
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT MAX(sequence_number) AS max_seq FROM event_log"
            ).fetchone()
            if row and row["max_seq"] is not None:
                self._sequence = row["max_seq"]
        finally:
            conn.close()

    @classmethod
    def get_instance(cls, db_path: Union[str, Path] | None = None) -> EventBus:
        """Return the singleton EventBus, creating it if necessary."""
        with cls._lock:
            if cls._instance is None:
                if db_path is None:
                    raise RuntimeError("EventBus not initialised — provide db_path")
                cls._instance = cls(db_path)
            return cls._instance

    @classmethod
    def reset(cls) -> None:
        """Reset the singleton (for testing)."""
        with cls._lock:
            cls._instance = None

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path)
        conn.execute("PRAGMA foreign_keys = ON")
        conn.row_factory = sqlite3.Row
        return conn

    def publish(self, event: Event) -> Event:
        """Assign a monotonic sequence_number, persist, and notify subscribers."""
        with self._seq_lock:
            self._sequence += 1
            event.sequence_number = self._sequence

        # Persist to SQLite
        conn = self._connect()
        try:
            conn.execute(
                "INSERT INTO event_log "
                "(event_id, event_type, timestamp, session_id, agent_did, payload, sequence_number) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    event.event_id,
                    event.event_type.value if isinstance(event.event_type, EventType) else event.event_type,
                    event.timestamp,
                    event.session_id,
                    event.agent_did,
                    json.dumps(event.payload),
                    event.sequence_number,
                ),
            )
            conn.commit()
        finally:
            conn.close()

        # Notify subscribers
        with self._sub_lock:
            subscribers = list(self._subscribers.values())

        for callback, event_filter in subscribers:
            if event_filter is None or event_filter(event):
                try:
                    callback(event)
                except Exception:
                    pass  # Don't let subscriber errors break the bus

        return event

    def subscribe(
        self,
        callback: Callable[[Event], Any],
        filter: Callable[[Event], bool] | None = None,
    ) -> str:
        """Register a subscriber. Returns a subscription ID."""
        with self._sub_lock:
            self._sub_id_counter += 1
            sub_id = f"sub-{self._sub_id_counter}"
            self._subscribers[sub_id] = (callback, filter)
        return sub_id

    def unsubscribe(self, subscription_id: str) -> None:
        """Remove a subscriber."""
        with self._sub_lock:
            self._subscribers.pop(subscription_id, None)

    def replay(
        self,
        since_sequence: int = 0,
        event_types: list[EventType] | None = None,
        session_id: str | None = None,
        agent_did: str | None = None,
        limit: int = 100,
    ) -> list[Event]:
        """Query persisted events with optional filters."""
        conn = self._connect()
        try:
            query = "SELECT * FROM event_log WHERE sequence_number > ?"
            params: list[Any] = [since_sequence]

            if event_types is not None:
                placeholders = ", ".join("?" for _ in event_types)
                query += f" AND event_type IN ({placeholders})"
                params.extend(
                    et.value if isinstance(et, EventType) else et
                    for et in event_types
                )

            if session_id is not None:
                query += " AND session_id = ?"
                params.append(session_id)

            if agent_did is not None:
                query += " AND agent_did = ?"
                params.append(agent_did)

            query += " ORDER BY sequence_number ASC LIMIT ?"
            params.append(limit)

            rows = conn.execute(query, params).fetchall()
            events: list[Event] = []
            for r in rows:
                payload = r["payload"]
                if isinstance(payload, str):
                    payload = json.loads(payload)
                events.append(
                    Event(
                        event_id=r["event_id"],
                        event_type=EventType(r["event_type"]),
                        timestamp=r["timestamp"],
                        session_id=r["session_id"],
                        agent_did=r["agent_did"],
                        payload=payload if payload else {},
                        sequence_number=r["sequence_number"],
                    )
                )
            return events
        finally:
            conn.close()
