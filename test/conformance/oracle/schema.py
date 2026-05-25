"""Pydantic types for the conformance fixture wire format and per-call results."""

from __future__ import annotations

from typing import Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, Field

Power = Literal["legislation", "execution", "adjudication", "support"]
StateDeltaKind = Literal[
    "mapping_set", "counter_inc", "counter_dec", "field_set",
    "array_push", "array_pop",
]
ResultKind = Literal["ok", "revert"]
Verdict = Literal["PASS", "FAIL", "GAP", "ERROR"]


class Source(BaseModel):
    model_config = ConfigDict(extra="forbid")
    foundry_test: str
    contracts_sha: str
    captured_at: str
    solc_version: str
    # Forge version metadata captured by the capture script (optional).
    forge_json_version: Optional[str] = None


class EmittedEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: Optional[str] = None
    args: dict[str, str | int | bool | list | dict | None] = Field(default_factory=dict)


class StateDelta(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: StateDeltaKind
    contract: str
    name: str
    key: Optional[str] = None       # for mapping_set / array_* (index)
    value: Optional[str] = None     # for mapping_set / field_set
    delta: Optional[str] = None     # for counter_inc / counter_dec


class CallResultPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: ResultKind
    # Foundry captures raw ABI-encoded bytes as a hex string; the oasis adapter
    # returns decoded values as a list of strings.  Both forms are valid here.
    return_data: Union[str, list[str]] = Field(default_factory=list)


class FixtureCall(BaseModel):
    model_config = ConfigDict(extra="forbid")
    idx: int
    target_contract: str
    # Raw on-chain address captured by the forge trace (optional; may differ from
    # target_contract when the contract is unlabeled).
    target_address: Optional[str] = None
    selector: str
    function: str                    # "name(types)" canonical form or raw selector hex
    args: list[str | int | bool | list | dict | None] = Field(default_factory=list)
    # Raw ABI-encoded calldata captured from the forge trace (optional).
    raw_calldata: Optional[str] = None
    msg_sender: str
    value_wei: str = "0"
    result: CallResultPayload
    events: list[EmittedEvent] = Field(default_factory=list)
    state_delta: list[StateDelta] = Field(default_factory=list)
    revert_reason: Optional[str] = None


class Fixture(BaseModel):
    model_config = ConfigDict(extra="forbid")
    fixture_version: Literal[1] = 1
    source: Source
    power: Power
    primary_contract: str
    # Forge test result status ("Success" / "Failure"), captured for diagnostics.
    test_status: Optional[str] = None
    calls: list[FixtureCall] = Field(default_factory=list)


# Runtime types (oasis-side capture)

class CallResult(BaseModel):
    """What the adapter returns after invoking an oasis function."""
    model_config = ConfigDict(extra="forbid")
    ok: bool
    revert: Optional[str] = None
    events: list[EmittedEvent] = Field(default_factory=list)
    state_delta: list[StateDelta] = Field(default_factory=list)


class CallVerdict(BaseModel):
    """The oracle's per-call verdict."""
    model_config = ConfigDict(extra="forbid")
    verdict: Verdict
    fixture_id: str            # e.g. "legislation/ConstitutionalParameters/test_setQuorum_happy"
    call_idx: int
    contract: str
    function: str
    power: Power
    diff: Optional[dict] = None  # structured diff payload when FAIL
    error: Optional[str] = None  # exception/trace when ERROR
