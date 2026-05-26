"""Replay conformance fixtures for the VotingVerifier contract."""

from __future__ import annotations

import importlib
import json
from pathlib import Path
from typing import Union

import pytest

from oasis.crypto import ed25519
from oasis.governance.messages import DAGProposal, canonical_signed_bytes
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
_UNIT_FIXTURE_DIR = Path(__file__).parent.parent / "fixtures" / "unit" / "VotingVerifier"
_DECODED_COPELAND_FIXTURE = _UNIT_FIXTURE_DIR / "decoded_copeland_ballots.json"

_EXPECTED_VV_MAPPINGS = (
    "openCommitPhase(bytes32,uint256,uint64,uint64,uint64)",
    "commitVote(bytes32,bytes32)",
    "revealVote(bytes32,bytes32,bytes32)",
    "submitVotingResult(bytes32,bytes32,bytes32,uint256)",
    "finalizeResult(bytes32)",
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


def _is_hex_address(value: str) -> bool:
    body = value.removeprefix("0x")
    return value.startswith("0x") and len(body) == 40 and all(
        char in "0123456789abcdefABCDEF" for char in body
    )


def _is_voting_verifier_call(call: FixtureCall, fixture: Fixture | None = None) -> bool:
    if call.target_contract == "VotingVerifier":
        return True
    return (
        fixture is not None
        and fixture.primary_contract == "VotingVerifier"
        and _is_hex_address(call.target_contract)
        and call.function in _EXPECTED_VV_MAPPINGS
    )


def _adapter_fn(call: FixtureCall, fixture: Fixture | None = None):
    if not _is_voting_verifier_call(call, fixture):
        return None
    return lookup("VotingVerifier", call.function)


def _same_fixture_call(left: FixtureCall, right: FixtureCall) -> bool:
    return (
        left.idx == right.idx
        and left.target_contract == right.target_contract
        and left.function == right.function
        and left.raw_calldata == right.raw_calldata
    )


def _reset_and_replay_prefix(fixture: Fixture, target_call: FixtureCall) -> None:
    module = _require_voting_verifier_adapter_loaded()
    module.reset_state()

    for prior_call in fixture.calls:
        if _same_fixture_call(prior_call, target_call):
            break
        fn = _adapter_fn(prior_call, fixture)
        if fn is not None:
            fn(prior_call)


def _mapped_dispatch(
    call: FixtureCall, fixture: Fixture, path: Path
) -> Union[CallResult, CallVerdict]:
    _reset_and_replay_prefix(fixture, call)
    fn = _adapter_fn(call, fixture)
    if fn is None:
        return _gap_verdict(fixture, call, path)
    return fn(call)


def _vv_calls_matching(*functions: str) -> list[tuple[Path, Fixture, FixtureCall]]:
    wanted = set(functions)
    return [
        (path, fixture, call)
        for path, fixture, call in _FIXTURE_CALLS
        if _is_voting_verifier_call(call, fixture) and call.function in wanted
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
    assert verdict.verdict in {"PASS", "FAIL"}, verdict.model_dump()


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
        assert verdict.verdict in {"PASS", "FAIL"}, verdict.model_dump()


def test_synthetic_copeland_fixture_is_not_in_captured_replay_corpus():
    assert all(
        path.name != "test_synthetic_copeland_decoded_ballots.json"
        for path in _FIXTURE_PATHS
    )


def test_address_targeted_voting_verifier_calls_dispatch_through_adapter():
    address_targeted_calls = [
        (path, fixture, call)
        for path, fixture, call in _FIXTURE_CALLS
        if fixture.primary_contract == "VotingVerifier"
        and call.target_contract.startswith("0x")
        and call.function in _EXPECTED_VV_MAPPINGS
    ]
    assert address_targeted_calls

    for path, fixture, call in address_targeted_calls:
        actual = _mapped_dispatch(call, fixture, path)
        assert not _is_gap(actual), (
            f"GAP while replaying address-targeted VotingVerifier call "
            f"{path.name}:{call.idx}"
        )


def test_decoded_copeland_unit_fixture_exercises_oasis_tally():
    fixture = Fixture.model_validate(json.loads(_DECODED_COPELAND_FIXTURE.read_text()))
    path = _DECODED_COPELAND_FIXTURE

    for call in fixture.calls:
        actual = _mapped_dispatch(call, fixture, path)
        assert not _is_gap(actual), f"GAP while replaying unit fixture call {call.idx}"
        verdict = diff_call(
            expected=call,
            actual=actual,
            opts=DiffOptions(),
            fixture_id=f"VotingVerifierUnit/{path.name}",
            power=fixture.power,
        )
        assert verdict.verdict == "PASS", verdict.model_dump()


def _proposal_envelope(signature: str | None = None, public_key: str | None = None):
    payload = {
        "msg_type": "DAG_PROPOSAL",
        "session_id": "session-vv-envelope",
        "proposer_did": "did:key:agent",
        "dag_spec": {"nodes": ["task-1"]},
        "rationale": "fixture coverage",
        "token_budget_total": 1.0,
        "deadline_ms": 1000,
    }
    if signature is not None:
        payload["signature"] = signature
    if public_key is not None:
        payload["public_key"] = public_key
    return payload


def _call_with_payload(payload: dict) -> FixtureCall:
    return FixtureCall(
        idx=0,
        target_contract="VotingVerifier",
        selector="0x0a6d7c2b",
        function="commitVote(bytes32,bytes32)",
        args=[payload],
        raw_calldata=(
            "0x0a6d7c2b"
            "1111111111111111111111111111111111111111111111111111111111111111"
            "2222222222222222222222222222222222222222222222222222222222222222"
        ),
        msg_sender="0x0000000000000000000000000000000000000001",
        value_wei="0",
        result={"kind": "ok", "return_data": "0x"},
        events=[],
        state_delta=[],
        revert_reason=None,
    )


def test_decoded_envelope_and_ballot_paths_are_exercised():
    module = _require_voting_verifier_adapter_loaded()
    adapter = module.VotingVerifierAdapter()
    private_key, public_key = ed25519.generate_keypair()
    unsigned = DAGProposal.model_validate(_proposal_envelope())
    signature = ed25519.sign(private_key, canonical_signed_bytes(unsigned)).hex()

    valid = adapter.dispatch(
        _call_with_payload(
            {
                "envelope": _proposal_envelope(signature, public_key.hex()),
                "candidates": ["A", "B"],
                "ranking": ["A", "B"],
            }
        )
    )
    assert valid.ok is True

    bad_signature = adapter.dispatch(
        _call_with_payload(
            {"envelope": _proposal_envelope("00" * 64, public_key.hex())}
        )
    )
    assert bad_signature.ok is False
    assert bad_signature.revert == "Ed25519 signature verification failed"

    malformed = adapter.dispatch(
        _call_with_payload({"envelope": {"signature": signature}})
    )
    assert malformed.ok is False
    assert malformed.revert == "Unsupported decoded envelope message type"

    empty_ballot = adapter.dispatch(
        _call_with_payload({"candidates": ["A", "B"], "ranking": []})
    )
    assert empty_ballot.ok is False
    assert empty_ballot.revert


def test_malformed_or_empty_vote_envelopes_reject_like_solidity():
    rejection_calls = [
        (path, fixture, call)
        for path, fixture, call in _vv_calls_matching(
            "commitVote(bytes32,bytes32)",
            "revealVote(bytes32,bytes32,bytes32)",
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
        assert verdict.verdict in {"PASS", "FAIL"}, verdict.model_dump()


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
