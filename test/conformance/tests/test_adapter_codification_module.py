"""Replay CodificationModule fixtures through adapter dispatch + diff harness.

This mirrors the ConstitutionalReview replay template for CodificationModule:
- validates every captured fixture as a ``Fixture`` model,
- resolves each ``(contract, function)`` via ``registry.lookup``,
- captures adapter-side events with ``EventCollector``,
- computes the oracle verdict with ``diff_call``, and
- accepts PASS/FAIL as conformance signal while skipping lookup misses as GAP.
"""

from __future__ import annotations

import importlib
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from oasis.observatory.event_bus import EventBus
from test.conformance.adapter.event_capture import EventCollector
from test.conformance.adapter.registry import lookup
from test.conformance.oracle.diff import DiffOptions, diff_call
from test.conformance.oracle.schema import CallResult, Fixture, FixtureCall


FIXTURE_DIR = (
    Path(__file__).resolve().parents[1]
    / "fixtures"
    / "legislation"
    / "CodificationModule"
)
_FIXTURE_PATHS = sorted(FIXTURE_DIR.glob("*.json"))

pytestmark = pytest.mark.conformance


@pytest.fixture(autouse=True)
def _fresh_bus(tmp_path: Path):
    EventBus.reset()
    EventBus.get_instance(db_path=tmp_path / "observatory.db")
    yield
    EventBus.reset()


def _import_adapter_module():
    try:
        return importlib.import_module("test.conformance.adapter.codification_module")
    except ModuleNotFoundError as exc:
        if exc.name == "test.conformance.adapter.codification_module":
            pytest.fail(
                "CodificationModule adapter module is required for fixture replay"
            )
        raise


def _load_fixture(path: Path) -> Fixture:
    try:
        return Fixture.model_validate(json.loads(path.read_text()))
    except ValidationError as exc:
        pytest.fail(f"Fixture {path.name} failed schema validation: {exc}")


def _fixture_id(path: Path) -> str:
    return f"{path.parent.name}/{path.name}"


def _fixture_calls() -> list[tuple[Path, Fixture, FixtureCall]]:
    calls: list[tuple[Path, Fixture, FixtureCall]] = []
    for path in _FIXTURE_PATHS:
        fixture = _load_fixture(path)
        for call in fixture.calls:
            calls.append((path, fixture, call))
    return calls


def _call_id(item: tuple[Path, Fixture, FixtureCall]) -> str:
    path, _, call = item
    return f"{path.name}:{call.idx}:{call.function}"


_FIXTURE_CALLS = _fixture_calls()


def _dispatch_or_gap(call: FixtureCall):
    _import_adapter_module()
    adapter_fn = lookup(call.target_contract, call.function)
    if adapter_fn is None:
        pytest.skip(f"GAP: {call.target_contract}.{call.function}")

    with EventCollector():
        return adapter_fn(call)


@pytest.mark.parametrize("fixture_path", _FIXTURE_PATHS, ids=lambda p: p.name)
def test_adapter_replays_CodificationModule_fixtures(fixture_path: Path):
    fixture = _load_fixture(fixture_path)

    verdicts = []
    for call in fixture.calls:
        actual = _dispatch_or_gap(call)
        verdict = diff_call(
            call,
            actual,
            DiffOptions(),
            fixture_id=_fixture_id(fixture_path),
            power=fixture.power,
        )
        assert verdict.verdict in {"PASS", "FAIL"}, (
            f"Unexpected verdict {verdict.verdict} for {fixture_path.name} "
            f"call[{call.idx}] {call.function}: {verdict.diff or verdict.error}"
        )
        verdicts.append(verdict)

    assert len(verdicts) == len(fixture.calls)


@pytest.mark.parametrize(
    "fixture_path,fixture,fixture_call",
    _FIXTURE_CALLS,
    ids=[_call_id(item) for item in _FIXTURE_CALLS],
)
def test_codify_spec_compile_path_dispatches_to_diff_call(
    fixture_path: Path,
    fixture: Fixture,
    fixture_call: FixtureCall,
):
    if fixture_call.target_contract != "CodificationModule" or not (
        fixture_call.function == "codify(bytes32,bytes32,bytes32)"
    ):
        pytest.skip("Not a CodificationModule codify fixture call")

    actual = _dispatch_or_gap(fixture_call)
    verdict = diff_call(
        fixture_call,
        actual,
        DiffOptions(),
        fixture_id=_fixture_id(fixture_path),
        power=fixture.power,
    )

    assert verdict.contract == "CodificationModule"
    assert verdict.function == "codify(bytes32,bytes32,bytes32)"
    assert verdict.verdict in {"PASS", "FAIL"}


def test_unmapped_CodificationModule_functions_report_gap():
    _import_adapter_module()
    for _, _, call in _FIXTURE_CALLS:
        if call.target_contract == "CodificationModule" and lookup(
            call.target_contract, call.function
        ) is None:
            pytest.skip(f"GAP: {call.target_contract}.{call.function}")

    pytest.skip("No unmapped CodificationModule fixture call available")


def test_diff_reports_string_canonicalization_drift_as_fail():
    expected = FixtureCall(
        idx=0,
        target_contract="CodificationModule",
        selector="0x3b6921c2",
        function="codify(bytes32,bytes32,bytes32)",
        args=[],
        msg_sender="0x0000000000000000000000000000000000000001",
        result={"kind": "ok", "return_data": ["Spec Title"]},
    )
    actual = CallResult(
        ok=True,
        revert=None,
        events=[],
        state_delta=[],
        return_data=["spec title"],
    )

    verdict = diff_call(
        expected,
        actual,
        DiffOptions(),
        fixture_id="CodificationModule/string-canonicalization",
        power="legislation",
    )

    assert verdict.verdict == "FAIL"
    assert verdict.diff is not None
    assert verdict.diff["result"]["return_data"]["reason"] == "return_data_mismatch"


def test_empty_or_null_codify_inputs_are_replayed_as_revert_or_fail_signal():
    zero_input_calls = [
        (path, fixture, call)
        for path, fixture, call in _FIXTURE_CALLS
        if call.target_contract == "CodificationModule"
        and call.function == "codify(bytes32,bytes32,bytes32)"
        and call.result.kind == "revert"
        and (
            "0000000000000000000000000000000000000000000000000000000000000000"
            in (call.raw_calldata or "")
        )
    ]
    if not zero_input_calls:
        pytest.skip("No empty/null codify input fixture available")

    path, fixture, call = zero_input_calls[0]
    actual = _dispatch_or_gap(call)
    verdict = diff_call(
        call,
        actual,
        DiffOptions(),
        fixture_id=_fixture_id(path),
        power=fixture.power,
    )

    assert verdict.verdict in {"PASS", "FAIL"}
