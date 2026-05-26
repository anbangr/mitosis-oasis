"""Replay ConstitutionalReview fixtures through adapter dispatch + diff harness.

For each fixture call:
- validates the fixture via the shared ``Fixture`` model,
- resolves ``(contract, function)`` via ``registry.lookup``,
- captures events with ``EventCollector``,
- computes fixture verdict with ``diff_call``, and
- asserts only ``PASS``/``FAIL`` verdicts (``FAIL`` is expected conformance signal).

If no adapter exists, the case is skipped as ``GAP: ...``.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from oasis.observatory.event_bus import EventBus
from test.conformance.adapter.event_capture import EventCollector
from test.conformance.adapter.constitutional_review import (
    _reset_state,
    events_from_bus,
)
from test.conformance.adapter.registry import lookup
from test.conformance.oracle.diff import DiffOptions, diff_call
from test.conformance.oracle.schema import Fixture

from test.conformance.adapter import constitutional_parameters  # noqa: F401
from test.conformance.adapter import constitutional_review  # noqa: F401

FIXTURE_DIR = (
    Path(__file__).resolve().parents[1]
    / "fixtures" / "legislation" / "ConstitutionalReview"
)
_FIXTURE_PATHS = sorted(FIXTURE_DIR.glob("*.json"))


@pytest.fixture(autouse=True)
def _fresh_bus_and_state(tmp_path: Path):
    EventBus.reset()
    EventBus.get_instance(db_path=tmp_path / "observatory.db")
    _reset_state()
    yield
    EventBus.reset()


def _fixture_id(path: Path) -> str:
    return f"{path.parent.name}/{path.name}"


@pytest.mark.parametrize("fixture_path", _FIXTURE_PATHS, ids=lambda p: p.name)
def test_adapter_replays_ConstitutionalReview_fixtures(fixture_path: Path):
    raw = fixture_path.read_text()
    try:
        fixture = Fixture.model_validate(json.loads(raw))
    except ValidationError as exc:
        pytest.fail(f"Fixture {fixture_path.name} failed schema validation: {exc}")

    fixture_id = _fixture_id(fixture_path)

    for call in fixture.calls:
        adapter_fn = lookup(call.target_contract, call.function)
        if adapter_fn is None:
            pytest.skip(
                f"GAP: missing adapter for {call.target_contract}.{call.function}"
            )

        with EventCollector() as collector:
            actual = adapter_fn(call)
        actual.events = events_from_bus(collector.events)

        verdict = diff_call(
            call,
            actual,
            DiffOptions(),
            fixture_id=fixture_id,
            power=fixture.power,
        )
        assert verdict.verdict in {"PASS", "FAIL"}, (
            f"Unexpected verdict {verdict.verdict} for {fixture_path.name} "
            f"call[{call.idx}] {call.function}: {verdict.diff or verdict.error}"
        )
