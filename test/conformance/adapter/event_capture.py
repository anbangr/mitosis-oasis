"""Context-managed subscriber that collects all oasis Events emitted inside a `with` block."""

from __future__ import annotations

from oasis.observatory.event_bus import EventBus
from oasis.observatory.events import Event


class EventCollector:
    """Collect oasis Events published inside the with-block.

    Usage:
        with EventCollector() as col:
            do_thing()
        assert col.events  # list[Event] in publish order
    """

    def __init__(self) -> None:
        self.events: list[Event] = []
        self._sub_id: str | None = None

    def __enter__(self) -> "EventCollector":
        try:
            bus = EventBus.get_instance()
        except RuntimeError as exc:
            raise RuntimeError(
                "EventCollector requires an initialised EventBus. "
                "Seed it in a pytest fixture: "
                "EventBus.get_instance(db_path=tmp_path / 'obs.db'). "
                f"Original error: {exc}"
            ) from exc
        self._sub_id = bus.subscribe(self._receive)
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        if self._sub_id is not None:
            EventBus.get_instance().unsubscribe(self._sub_id)
            self._sub_id = None

    def _receive(self, event: Event) -> None:
        self.events.append(event)
