"""Replay conformance fixtures for the LegislativePipeline contract."""

from __future__ import annotations

import json
from typing import Union
from pathlib import Path

import pytest

from test.conformance.adapter.legislative_pipeline import LegislativePipelineAdapter
from test.conformance.adapter.registry import lookup
from test.conformance.oracle.diff import DiffOptions, diff_call
from test.conformance.oracle.schema import (
    CallResult,
    CallVerdict,
    Fixture,
    FixtureCall,
)


_FIXTURE_DIR = (
    Path(__file__).parent.parent / "fixtures" / "legislation" / "LegislativePipeline"
)
_FIXTURE_PATHS = sorted(_FIXTURE_DIR.glob("*.json")) if _FIXTURE_DIR.exists() else []


def _load_fixture_calls() -> list[tuple[Path, Fixture, FixtureCall]]:
    calls: list[tuple[Path, Fixture, FixtureCall]] = []
    for path in _FIXTURE_PATHS:
        raw = json.loads(path.read_text())
        fixture = Fixture.model_validate(raw)
        for call in fixture.calls:
            calls.append((path, fixture, call))
    return calls


_FIXTURE_CALLS = _load_fixture_calls()


def _gap_verdict(
    fixture: Fixture, call: FixtureCall, fixture_path: Path
) -> CallVerdict:
    return CallVerdict(
        verdict="GAP",
        fixture_id=str(fixture_path.name),
        call_idx=call.idx,
        contract=call.target_contract,
        function=call.function,
        power=fixture.power,
        diff=None,
        error=f"GAP: {call.target_contract}.{call.function}",
    )


def _call_id(item: tuple[Path, Fixture, FixtureCall]) -> str:
    path, _, call = item
    return f"{path.name}:{call.idx}:{call.function}"


def _mapped_dispatch(call: FixtureCall, fixture: Fixture, path: Path):
    fn = (
        lookup("LegislativePipeline", call.function)
        if call.target_contract == "LegislativePipeline"
        else None
    )
    if fn is None:
        return _gap_verdict(fixture, call, path)
    return fn(call)


def _is_gap(result: Union[CallResult, CallVerdict]) -> bool:
    return isinstance(result, CallVerdict) and result.verdict == "GAP"


@pytest.mark.conformance
@pytest.mark.parametrize(
    "fixture_path,fixture,fixture_call",
    _FIXTURE_CALLS,
    ids=[_call_id(item) for item in _FIXTURE_CALLS],
)
def test_replay_legislative_pipeline_fixture_calls(
    fixture_path: Path,
    fixture: Fixture,
    fixture_call: FixtureCall,
):
    actual = _mapped_dispatch(fixture_call, fixture, fixture_path)

    if fixture_call.target_contract != "LegislativePipeline":
        assert _is_gap(actual)
        assert (
            actual.error
            == f"GAP: {fixture_call.target_contract}.{fixture_call.function}"
        )
        return

    if _is_gap(actual):
        return

    verdict = diff_call(
        expected=fixture_call,
        actual=actual,
        opts=DiffOptions(),
        fixture_id=fixture_path.name,
        power=fixture.power,
    )
    assert verdict.verdict == "PASS", verdict.model_dump()


@pytest.mark.conformance
def test_adapter_registry_is_import_time_ready():
    adapter = LegislativePipelineAdapter()
    assert adapter.contract == "LegislativePipeline"
    assert (
        lookup(
            "LegislativePipeline",
            "submitProposal(uint256,bytes32,(uint8,bytes32,bytes32,address,uint256,uint256)[5])",
        )
        is not None
    )
    assert lookup("LegislativePipeline", "setQuorumBps(uint256)") is not None
    assert lookup("LegislativePipeline", "advanceToRatification(bytes32)") is not None


@pytest.mark.conformance
def test_submit_proposal_fixture_path_uses_adapter_and_passes_events():
    proposal_calls = [
        (path, fixture, call)
        for path, fixture, call in _FIXTURE_CALLS
        if call.target_contract == "LegislativePipeline"
        and call.function.startswith("submitProposal(")
    ]
    if not proposal_calls:
        pytest.skip("No fixture submitProposal call available")

    path, fixture, fixture_call = proposal_calls[0]
    actual = _mapped_dispatch(fixture_call, fixture, path)
    assert not _is_gap(actual)
    assert actual.events == fixture_call.events
    assert [e.name for e in actual.events] == [e.name for e in fixture_call.events]


@pytest.mark.conformance
def test_revert_fixtures_compare_via_return_data():
    revert_calls = [
        (path, fixture, call)
        for path, fixture, call in _FIXTURE_CALLS
        if call.target_contract == "LegislativePipeline"
        and call.result.kind == "revert"
    ]
    if not revert_calls:
        pytest.skip("No revert LegislativePipeline fixture call available")

    path, fixture, fixture_call = revert_calls[0]
    actual = _mapped_dispatch(fixture_call, fixture, path)
    if _is_gap(actual):
        pytest.skip(
            f"Mapped revert fixture not available: {path.name}:{fixture_call.function}"
        )

    verdict = diff_call(
        expected=fixture_call,
        actual=actual,
        opts=DiffOptions(),
        fixture_id=path.name,
        power=fixture.power,
    )
    assert verdict.verdict == "PASS", verdict.model_dump()
    assert verdict.diff is None


@pytest.mark.conformance
def test_unmapped_lp_calls_report_gap():
    unmapped_calls = [
        (path, fixture, call)
        for path, fixture, call in _FIXTURE_CALLS
        if call.target_contract == "LegislativePipeline"
        and lookup("LegislativePipeline", call.function) is None
    ]
    if not unmapped_calls:
        pytest.skip("No unmapped LegislativePipeline function in fixtures")

    path, fixture, call = unmapped_calls[0]
    verdict = _mapped_dispatch(call, fixture, path)
    assert verdict.verdict == "GAP"
    assert verdict.error == f"GAP: {call.target_contract}.{call.function}"


@pytest.mark.conformance
def test_event_order_from_replayed_fixture_is_preserved():
    ordered_events_calls = [
        (path, fixture, call)
        for path, fixture, call in _FIXTURE_CALLS
        if call.target_contract == "LegislativePipeline" and len(call.events) > 1
    ]
    if not ordered_events_calls:
        pytest.skip("No multi-event LegislativePipeline fixture call available")

    path, fixture, call = ordered_events_calls[0]
    actual = _mapped_dispatch(call, fixture, path)
    assert not isinstance(actual, CallVerdict) or actual.verdict != "ERROR"
    assert [e.name for e in actual.events] == [e.name for e in call.events]
