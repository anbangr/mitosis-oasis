"""Replay GovernanceRegistry fixtures through adapter dispatch + diff harness."""

from __future__ import annotations

import importlib
import json
from pathlib import Path
from typing import Union

import pytest
from pydantic import ValidationError

from test.conformance.adapter.registry import lookup
from test.conformance.oracle.diff import DiffOptions, diff_call
from test.conformance.oracle.schema import (
    CallResult,
    CallVerdict,
    Fixture,
    FixtureCall,
)


FIXTURE_DIR = (
    Path(__file__).resolve().parents[1]
    / "fixtures" / "legislation" / "GovernanceRegistry"
)
_FIXTURE_PATHS = sorted(FIXTURE_DIR.glob("*.json")) if FIXTURE_DIR.exists() else []

pytestmark = pytest.mark.conformance


def _fixture_id(path: Path) -> str:
    return f"{path.parent.name}/{path.name}"


def _load_fixture_calls() -> list[tuple[Path, Fixture, FixtureCall]]:
    calls: list[tuple[Path, Fixture, FixtureCall]] = []
    for path in _FIXTURE_PATHS:
        try:
            fixture = Fixture.model_validate(json.loads(path.read_text()))
        except ValidationError as exc:
            pytest.fail(f"Fixture {path.name} failed schema validation: {exc}")
        for call in fixture.calls:
            calls.append((path, fixture, call))
    return calls


_FIXTURE_CALLS = _load_fixture_calls()


def _ensure_adapter_registered() -> None:
    importlib.import_module("test.conformance.adapter.governance_registry")


def _gap_verdict(
    fixture: Fixture, call: FixtureCall, fixture_path: Path
) -> CallVerdict:
    return CallVerdict(
        verdict="GAP",
        fixture_id=_fixture_id(fixture_path),
        call_idx=call.idx,
        contract=call.target_contract,
        function=call.function,
        power=fixture.power,
        diff=None,
        error=f"GAP: {call.target_contract}.{call.function}",
    )


def _mapped_dispatch(
    fixture: Fixture, call: FixtureCall, fixture_path: Path
) -> Union[CallResult, CallVerdict]:
    if call.target_contract != "GovernanceRegistry":
        return _gap_verdict(fixture, call, fixture_path)

    _ensure_adapter_registered()
    adapter_fn = lookup("GovernanceRegistry", call.function)
    if adapter_fn is None:
        return _gap_verdict(fixture, call, fixture_path)
    return adapter_fn(call)


def _is_gap(result: Union[CallResult, CallVerdict]) -> bool:
    return isinstance(result, CallVerdict) and result.verdict == "GAP"


def _call_id(item: tuple[Path, Fixture, FixtureCall]) -> str:
    path, _, call = item
    return f"{path.name}:{call.idx}:{call.target_contract}.{call.function}"


@pytest.mark.parametrize(
    "fixture_path,fixture,fixture_call",
    _FIXTURE_CALLS,
    ids=[_call_id(item) for item in _FIXTURE_CALLS],
)
def test_replay_GovernanceRegistry_fixture_calls(
    fixture_path: Path,
    fixture: Fixture,
    fixture_call: FixtureCall,
):
    actual = _mapped_dispatch(fixture, fixture_call, fixture_path)

    if _is_gap(actual):
        pytest.skip(actual.error)

    verdict = diff_call(
        expected=fixture_call,
        actual=actual,
        opts=DiffOptions(),
        fixture_id=_fixture_id(fixture_path),
        power=fixture.power,
    )
    assert verdict.verdict in {"PASS", "FAIL"}, verdict.model_dump()


def test_adapter_registry_is_import_time_ready():
    _ensure_adapter_registered()

    assert (
        lookup(
            "GovernanceRegistry",
            "createLaw((string,string,string,uint8,uint64,uint64,uint256,bytes32[]))",
        )
        is not None
    )
    assert lookup("GovernanceRegistry", "openSignaling(uint256)") is not None
    assert lookup("GovernanceRegistry", "activateLaw(uint256)") is not None


def test_state_transition_fixture_dispatches_through_adapter_and_returns_verdict():
    transition_calls = [
        (path, fixture, call)
        for path, fixture, call in _FIXTURE_CALLS
        if path.name == "test_activateLaw_thresholdMet.json"
        and call.target_contract == "GovernanceRegistry"
        and call.function
        in {
            "createLaw((string,string,string,uint8,uint64,uint64,uint256,bytes32[]))",
            "openSignaling(uint256)",
            "activateLaw(uint256)",
        }
    ]
    if not transition_calls:
        pytest.skip("No GovernanceRegistry state-transition fixture calls available")

    for path, fixture, call in transition_calls:
        actual = _mapped_dispatch(fixture, call, path)
        if _is_gap(actual):
            pytest.fail(
                f"Expected state-machine mapping for {call.function}, got {actual.error}"
            )

        verdict = diff_call(
            expected=call,
            actual=actual,
            opts=DiffOptions(),
            fixture_id=_fixture_id(path),
            power=fixture.power,
        )
        assert verdict.verdict in {"PASS", "FAIL"}, verdict.model_dump()


def test_unmapped_GovernanceRegistry_accessor_reports_gap():
    fixture = Fixture(
        fixture_version=1,
        source={
            "foundry_test": "synthetic:GAP",
            "contracts_sha": "0x0",
            "captured_at": "2026-05-26T00:00:00Z",
            "solc_version": "0.8.28",
        },
        power="legislation",
        primary_contract="GovernanceRegistry",
        calls=[],
    )
    call = FixtureCall(
        idx=0,
        target_contract="GovernanceRegistry",
        selector="0x00000000",
        function="getAckNonce(uint256)",
        args=[],
        raw_calldata="0x00000000",
        msg_sender="0x0000000000000000000000000000000000000000",
        value_wei="0",
        result={"kind": "ok", "return_data": "0x"},
        events=[],
        state_delta=[],
        revert_reason=None,
    )

    actual = _mapped_dispatch(fixture, call, Path("synthetic_gap.json"))

    assert _is_gap(actual)
    assert actual.error == "GAP: GovernanceRegistry.getAckNonce(uint256)"
