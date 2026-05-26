"""Replay conformance fixtures for the VotingVerifier contract."""

from __future__ import annotations

import importlib
import json
from pathlib import Path
from typing import Union

import pytest

from test.conformance.adapter.registry import lookup
from test.conformance.oracle.diff import DiffOptions, diff_call
from test.conformance.oracle.schema import (
    CallResult,
    CallVerdict,
    Fixture,
    FixtureCall,
)


_FIXTURE_DIR = (
    Path(__file__).parent.parent / "fixtures" / "legislation" / "VotingVerifier"
)
_FIXTURE_PATHS = sorted(_FIXTURE_DIR.glob("*.json")) if _FIXTURE_DIR.exists() else []

_EXPECTED_VV_MAPPINGS = (
    "openCommitPhase(bytes32,uint256,uint64,uint64,uint64)",
    "commitVote(bytes32,bytes32)",
    "revealVote(bytes32,bytes32,bytes32)",
    "submitVotingResult(bytes32,bytes32,bytes32,uint256)",
    "finalizeResult(bytes32)",
    "submitVotingProof(bytes32,bytes32,uint256,uint256)",
)


def _load_fixture_calls() -> list[tuple[Path, Fixture, FixtureCall]]:
    calls: list[tuple[Path, Fixture, FixtureCall]] = []
    for path in _FIXTURE_PATHS:
        fixture = Fixture.model_validate(json.loads(path.read_text()))
        for call in fixture.calls:
            calls.append((path, fixture, call))
    return calls


_FIXTURE_CALLS = _load_fixture_calls()


def _require_voting_verifier_adapter_loaded():
    try:
        return importlib.import_module("test.conformance.adapter.voting_verifier")
    except ModuleNotFoundError as exc:
        if exc.name == "test.conformance.adapter.voting_verifier":
            pytest.fail(
                "Missing VotingVerifier adapter module: "
                "test.conformance.adapter.voting_verifier"
            )
        raise


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


def _is_gap(result: Union[CallResult, CallVerdict]) -> bool:
    return isinstance(result, CallVerdict) and result.verdict == "GAP"


def _mapped_dispatch(
    call: FixtureCall, fixture: Fixture, path: Path
) -> Union[CallResult, CallVerdict]:
    _require_voting_verifier_adapter_loaded()
    fn = (
        lookup("VotingVerifier", call.function)
        if call.target_contract == "VotingVerifier"
        else None
    )
    if fn is None:
        return _gap_verdict(fixture, call, path)
    return fn(call)


def _vv_calls_matching(*functions: str) -> list[tuple[Path, Fixture, FixtureCall]]:
    wanted = set(functions)
    return [
        (path, fixture, call)
        for path, fixture, call in _FIXTURE_CALLS
        if call.target_contract == "VotingVerifier" and call.function in wanted
    ]


pytestmark = pytest.mark.conformance


@pytest.mark.parametrize(
    "fixture_path,fixture,fixture_call",
    _FIXTURE_CALLS,
    ids=[_call_id(item) for item in _FIXTURE_CALLS],
)
def test_replay_voting_verifier_fixture_calls(
    fixture_path: Path,
    fixture: Fixture,
    fixture_call: FixtureCall,
):
    actual = _mapped_dispatch(fixture_call, fixture, fixture_path)

    if _is_gap(actual):
        assert (
            actual.error
            == f"GAP: {fixture_call.target_contract}.{fixture_call.function}"
        )
        return

    verdict = diff_call(
        expected=fixture_call,
        actual=actual,
        opts=DiffOptions(),
        fixture_id=f"VotingVerifier/{fixture_path.name}",
        power=fixture.power,
    )
    assert verdict.verdict == "PASS", verdict.model_dump()


def test_adapter_registry_is_import_time_ready_for_voting_verifier():
    module = _require_voting_verifier_adapter_loaded()
    adapter = module.VotingVerifierAdapter()

    assert adapter.contract == "VotingVerifier"
    for function in _EXPECTED_VV_MAPPINGS:
        assert lookup("VotingVerifier", function) is not None


def test_copeland_tally_fixtures_match_solidity_or_surface_explicit_diff():
    tally_calls = _vv_calls_matching(
        "submitVotingResult(bytes32,bytes32,bytes32,uint256)",
        "finalizeResult(bytes32)",
    )
    if not tally_calls:
        pytest.skip("No VotingVerifier tally fixture calls available")

    for path, fixture, call in tally_calls:
        actual = _mapped_dispatch(call, fixture, path)
        assert not _is_gap(actual), (
            f"GAP while replaying tally fixture {path.name}:{call.idx}"
        )

        verdict = diff_call(
            expected=call,
            actual=actual,
            opts=DiffOptions(),
            fixture_id=f"VotingVerifier/{path.name}",
            power=fixture.power,
        )
        assert verdict.verdict == "PASS", verdict.model_dump()


def test_malformed_or_empty_vote_envelopes_reject_like_solidity():
    rejection_calls = [
        (path, fixture, call)
        for path, fixture, call in _vv_calls_matching(
            "commitVote(bytes32,bytes32)",
            "revealVote(bytes32,bytes32,bytes32)",
            "submitVotingProof(bytes32,bytes32,uint256,uint256)",
        )
        if call.result.kind == "revert"
    ]
    if not rejection_calls:
        pytest.skip("No malformed VotingVerifier envelope rejection fixtures available")

    for path, fixture, call in rejection_calls:
        actual = _mapped_dispatch(call, fixture, path)
        assert not _is_gap(actual), (
            f"GAP while replaying envelope rejection fixture {path.name}:{call.idx}"
        )

        verdict = diff_call(
            expected=call,
            actual=actual,
            opts=DiffOptions(),
            fixture_id=f"VotingVerifier/{path.name}",
            power=fixture.power,
        )
        assert verdict.verdict == "PASS", verdict.model_dump()


def test_unmapped_voting_verifier_functions_report_gap():
    _require_voting_verifier_adapter_loaded()
    unmapped_calls = [
        (path, fixture, call)
        for path, fixture, call in _FIXTURE_CALLS
        if call.target_contract == "VotingVerifier"
        and call.function not in _EXPECTED_VV_MAPPINGS
        and lookup("VotingVerifier", call.function) is None
    ]
    if not unmapped_calls:
        pytest.skip("No unmapped VotingVerifier function in fixtures")

    path, fixture, call = unmapped_calls[0]
    verdict = _mapped_dispatch(call, fixture, path)
    assert verdict.verdict == "GAP"
    assert verdict.error == f"GAP: {call.target_contract}.{call.function}"
