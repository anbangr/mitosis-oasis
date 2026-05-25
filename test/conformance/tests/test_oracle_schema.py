"""Schema validation for fixture JSON."""

import json
import pytest
from pydantic import ValidationError

from test.conformance.oracle.schema import Fixture, FixtureCall, StateDelta, EmittedEvent


def test_fixture_parses_minimal_valid_payload():
    payload = {
        "fixture_version": 1,
        "source": {
            "foundry_test": "ConstitutionalParametersTest::test_setQuorum_happy",
            "contracts_sha": "0xabc",
            "captured_at": "2026-05-25T12:00:00Z",
            "solc_version": "0.8.28",
        },
        "power": "legislation",
        "primary_contract": "ConstitutionalParameters",
        "calls": [],
    }
    fixture = Fixture.model_validate(payload)
    assert fixture.power == "legislation"
    assert fixture.primary_contract == "ConstitutionalParameters"


def test_fixture_rejects_unknown_power():
    payload = {
        "fixture_version": 1,
        "source": {
            "foundry_test": "x",
            "contracts_sha": "0x0",
            "captured_at": "2026-05-25T12:00:00Z",
            "solc_version": "0.8.28",
        },
        "power": "constitutional",  # invalid
        "primary_contract": "X",
        "calls": [],
    }
    with pytest.raises(ValidationError):
        Fixture.model_validate(payload)


def test_call_round_trip():
    call = FixtureCall(
        idx=0,
        target_contract="ConstitutionalParameters",
        selector="0x12345678",
        function="setQuorum(uint256)",
        args=["100"],
        msg_sender="0xowner",
        value_wei="0",
        result={"kind": "ok", "return_data": []},
        events=[EmittedEvent(name="QuorumSet", args={"quorum": "100"})],
        state_delta=[
            StateDelta(kind="field_set", contract="ConstitutionalParameters",
                       name="quorum", key=None, value="100", delta=None)
        ],
        revert_reason=None,
    )
    blob = call.model_dump_json()
    round_tripped = FixtureCall.model_validate_json(blob)
    assert round_tripped == call


def test_state_delta_rejects_unknown_kind():
    with pytest.raises(ValidationError):
        StateDelta.model_validate({"kind": "alien_kind", "contract": "X", "name": "y"})
