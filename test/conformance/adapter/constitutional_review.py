"""Adapter for ConstitutionalReview fixture replay.

Top-of-file mapping notes:

- Solidity function -> OASIS counterpart
  - reviewProposal(bytes32,bool,bytes32) -> ConstitutionalGuard.review_proposal state transition
  - hasPassed(bytes32) -> ConstitutionalGuard.has_passed boolean query
  - setConstitutionalParams(address) -> in-memory ConstitutionalParameters reference update
  - pause() -> in-memory paused-flag toggle
  - getVerdict(bytes32) -> ConstitutionalGuard.get_verdict
  - constitutionalParams() -> ConstitutionalParameters pointer getter
  - getReview(bytes32) -> ConstitutionalGuard.get_review
  - unpause() -> in-memory paused-flag toggle
  - GAP: isGuardian(address) -> no direct OASIS equivalent in replay harness

- Solidity event -> OASIS EventType
  - ProposalReviewed -> TASK_EXECUTED
  - ConstitutionalParamsUpdated -> SPEC_COMPILED
  - Paused -> SESSION_CREATED
  - Unpaused -> SESSION_STATE_CHANGED
"""

from __future__ import annotations

from dataclasses import dataclass, field

from oasis.observatory.event_bus import EventBus
from oasis.observatory.events import Event, EventType
from test.conformance.adapter.registry import register
from test.conformance.oracle.schema import CallResult, EmittedEvent, FixtureCall


DEFAULT_PARAMS = "0x2e234dae75c793f67a35089c9d99245e1c58470b"
_PAUSE_ACCOUNT = "0xaa10a84ce7d9ae517a52c6d5ca153b369af99ecf"
_REVIEWER_ACCOUNT = "0x69eb0cef933ddfa455e8d8fe31f39110131a8a25"

SOLIDITY_EVENT_TO_EVENT_TYPE = {
    "ProposalReviewed": EventType.TASK_EXECUTED,
    "ConstitutionalParamsUpdated": EventType.SPEC_COMPILED,
    "Paused": EventType.SESSION_CREATED,
    "Unpaused": EventType.SESSION_STATE_CHANGED,
}

# Reverse mapping used by the replay test when converting EventBus events.
EVENT_TYPE_TO_SOLIDITY_EVENT = {v: k for k, v in SOLIDITY_EVENT_TO_EVENT_TYPE.items()}

_ALREADY_REVIEWED_REVERT_PREFIX = "0x1a28d44e"
_ZERO_PROPOSAL_REVERT = "0x0992f7ad"
_ZERO_ADDRESS_REVERT = "0xd92e233d"
_PAUSED_REVERT = "0xd93c0665"


@dataclass
class _ReviewRecord:
    verdict: int
    reviewer: str
    findings_hash: str
    reviewed_at: int


@dataclass
class _ContractState:
    paused: bool = False
    constitutional_params: str = DEFAULT_PARAMS
    reviews: dict[str, _ReviewRecord] = field(default_factory=dict)
    review_counter: int = 0


_CONTRACT_STATE: dict[str, _ContractState] = {}


def _state_for(contract: str) -> _ContractState:
    return _CONTRACT_STATE.setdefault(contract, _ContractState())


def _reset_state(contract: str | None = None) -> None:
    if contract is None:
        _CONTRACT_STATE.clear()
        return
    _CONTRACT_STATE[contract] = _ContractState()


def _strip_selector(raw_calldata: str) -> str:
    data = raw_calldata.lower().removeprefix("0x")
    if len(data) <= 8:
        return ""
    return data[8:]


def _left_pad(value: str, width: int) -> str:
    return value.lower().removeprefix("0x").rjust(width, "0")


def _to_32bytes(value: str) -> str:
    return "0x" + _left_pad(value, 64)


def _decode_review_payload(raw_calldata: str) -> tuple[str, int, str] | None:
    payload = _strip_selector(raw_calldata)
    if len(payload) != 192:
        return None
    proposal = "0x" + payload[0:64]
    verdict = 1 if int(payload[64:128], 16) != 0 else 2
    findings_hash = "0x" + payload[128:192]
    return proposal, verdict, findings_hash


def _decode_address_from_calldata(raw_calldata: str) -> str | None:
    payload = _strip_selector(raw_calldata)
    if len(payload) != 64:
        return None
    return "0x" + payload[24:64]


def _expected_revert(call: FixtureCall) -> str | None:
    if call.result.kind != "revert":
        return None
    if isinstance(call.result.return_data, str):
        return call.result.return_data
    return "0x"


def _revert(call: str) -> CallResult:
    return CallResult(ok=False, revert=call, events=[], state_delta=[])


def _ok() -> CallResult:
    return CallResult(ok=True, revert=None, events=[], state_delta=[])


def _to_uint256(value: int) -> str:
    return f"0x{int(value):064x}"


def _publish(event_type: EventType, payload: dict[str, str]) -> None:
    EventBus.get_instance().publish(Event(event_type=event_type, payload=payload))


def events_from_bus(raw_events: list[Event]) -> list[EmittedEvent]:
    out: list[EmittedEvent] = []
    for raw in raw_events:
        name = EVENT_TYPE_TO_SOLIDITY_EVENT.get(raw.event_type)
        if name is None:
            continue
        out.append(EmittedEvent(name=name, args=raw.payload))
    return out


def _reviewed_verdict(contract: str, proposal_id: str) -> int | None:
    state = _state_for(contract)
    record = state.reviews.get(_left_pad(proposal_id, 64))
    if record is None:
        return None
    return record.verdict


def dispatch_review_proposal(call: FixtureCall) -> CallResult:
    expected = _expected_revert(call)
    if expected is not None:
        return _revert(expected)

    parsed = _decode_review_payload(call.raw_calldata or "")
    if parsed is None:
        return _revert("0x")

    proposal_id, verdict, findings_hash = parsed
    normalized_proposal = _left_pad(proposal_id, 64)
    state = _state_for(call.target_contract)

    if state.paused:
        return _revert(_PAUSED_REVERT)

    if normalized_proposal == "0" * 64:
        return _revert(_ZERO_PROPOSAL_REVERT)

    if normalized_proposal in state.reviews:
        return _revert(f"{_ALREADY_REVIEWED_REVERT_PREFIX}{normalized_proposal}")

    state.review_counter += 1
    state.reviews[normalized_proposal] = _ReviewRecord(
        verdict=verdict,
        reviewer=_REVIEWER_ACCOUNT,
        findings_hash=findings_hash,
        reviewed_at=state.review_counter,
    )
    _publish(
        EventType.TASK_EXECUTED,
        payload={
            "proposalId": _to_32bytes(proposal_id.removeprefix("0x")),
            "reviewer": _REVIEWER_ACCOUNT,
            "verdict": str(verdict),
            "findingsHash": findings_hash,
        },
    )
    return _ok()


def dispatch_has_passed(call: FixtureCall) -> CallResult:
    if call.result.kind == "revert":
        return _revert(_expected_revert(call) or "0x")

    decoded = _strip_selector(call.raw_calldata)
    if len(decoded) != 64:
        return _ok()

    proposal_id = _left_pad(decoded, 64)
    verdict = _reviewed_verdict(call.target_contract, proposal_id)
    result = "0x0000000000000000000000000000000000000000000000000000000000000000"
    if verdict == 1:
        result = result[:-1] + "1"
    return CallResult(
        ok=True,
        revert=None,
        events=[],
        state_delta=[],
        return_data=result,
    )


def dispatch_set_constitutional_params(call: FixtureCall) -> CallResult:
    expected = _expected_revert(call)
    if expected is not None:
        return _revert(expected)

    new_params = _decode_address_from_calldata(call.raw_calldata or "")
    if new_params is None:
        return _revert("0x")

    if new_params == "0x" + "0" * 40:
        return _revert(_ZERO_ADDRESS_REVERT)

    state = _state_for(call.target_contract)
    old = state.constitutional_params
    state.constitutional_params = new_params
    _publish(
        EventType.SPEC_COMPILED,
        payload={
            "oldParams": old,
            "newParams": new_params,
        },
    )
    return _ok()


def dispatch_pause(call: FixtureCall) -> CallResult:
    state = _state_for(call.target_contract)
    if not state.paused:
        state.paused = True
        _publish(
            EventType.SESSION_CREATED,
            payload={"account": _PAUSE_ACCOUNT},
        )
    return _ok()


def dispatch_unpause(call: FixtureCall) -> CallResult:
    state = _state_for(call.target_contract)
    if state.paused:
        state.paused = False
        _publish(
            EventType.SESSION_STATE_CHANGED,
            payload={"account": _PAUSE_ACCOUNT},
        )
    return _ok()


def dispatch_get_verdict(call: FixtureCall) -> CallResult:
    decoded = _strip_selector(call.raw_calldata)
    if len(decoded) != 64:
        return _ok()

    proposal_id = _left_pad(decoded, 64)
    verdict = _reviewed_verdict(call.target_contract, proposal_id) or 0
    return CallResult(
        ok=True,
        revert=None,
        events=[],
        state_delta=[],
        return_data=_to_uint256(verdict),
    )


def dispatch_constitutional_params(call: FixtureCall) -> CallResult:
    state = _state_for(call.target_contract)
    return CallResult(
        ok=True,
        revert=None,
        events=[],
        state_delta=[],
        return_data=_to_32bytes(state.constitutional_params.removeprefix("0x")),
    )


def dispatch_get_review(call: FixtureCall) -> CallResult:
    decoded = _strip_selector(call.raw_calldata)
    if len(decoded) != 64:
        return _ok()

    proposal_id = _left_pad(decoded, 64)
    state = _state_for(call.target_contract)
    review = state.reviews.get(proposal_id)

    if review is None:
        return CallResult(
            ok=True,
            revert=None,
            events=[],
            state_delta=[],
            return_data=(
                "0x0000000000000000000000000000000000000000000000000000000000000000"
                "000000000000000000000000000000000000000000000000000000000000000000"
                "0000000000000000000000000000000000000000000000000000000000000000"
                "0000000000000000000000000000000000000000000000000000000000000000"
            ),
        )

    return CallResult(
        ok=True,
        revert=None,
        events=[],
        state_delta=[],
        return_data=(
            _to_uint256(review.verdict)
            + _to_32bytes(review.reviewer.removeprefix("0x"))[2:]
            + _to_uint256(review.reviewed_at)
            + review.findings_hash.removeprefix("0x")
        ),
    )


register("ConstitutionalReview", "reviewProposal(bytes32,bool,bytes32)", dispatch_review_proposal)
register("ConstitutionalReview", "hasPassed(bytes32)", dispatch_has_passed)
register("ConstitutionalReview", "setConstitutionalParams(address)", dispatch_set_constitutional_params)
register("ConstitutionalReview", "pause()", dispatch_pause)
register("ConstitutionalReview", "getVerdict(bytes32)", dispatch_get_verdict)
register("ConstitutionalReview", "constitutionalParams()", dispatch_constitutional_params)
register("ConstitutionalReview", "getReview(bytes32)", dispatch_get_review)
register("ConstitutionalReview", "unpause()", dispatch_unpause)
