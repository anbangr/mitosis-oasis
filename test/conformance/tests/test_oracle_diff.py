"""Unit tests for the oracle diff."""

from test.conformance.oracle.diff import DiffOptions, diff_call
from test.conformance.oracle.schema import (
    CallResult, CallResultPayload, EmittedEvent, FixtureCall, StateDelta,
)


def _fix(events=None, state=None, kind="ok", revert=None):
    return FixtureCall(
        idx=0,
        target_contract="X",
        selector="0x0",
        function="f()",
        args=[],
        msg_sender="0x0",
        value_wei="0",
        result=CallResultPayload(kind=kind, return_data=[]),
        events=events or [],
        state_delta=state or [],
        revert_reason=revert,
    )


def _act(events=None, state=None, ok=True, revert=None):
    return CallResult(
        ok=ok, revert=revert,
        events=events or [], state_delta=state or [],
    )


def test_identical_inputs_pass():
    ev = [EmittedEvent(name="A", args={"x": "1"})]
    st = [StateDelta(kind="field_set", contract="X", name="q", value="1")]
    v = diff_call(_fix(ev, st), _act(ev, st), DiffOptions())
    assert v.verdict == "PASS"
    assert v.diff is None


def test_missing_event_fails():
    ev_expected = [EmittedEvent(name="A", args={})]
    v = diff_call(_fix(ev_expected, []), _act([], []), DiffOptions())
    assert v.verdict == "FAIL"
    assert v.diff is not None
    assert "events" in v.diff


def test_extra_event_fails_by_default_strict_event_set():
    ev_extra = [EmittedEvent(name="A", args={}), EmittedEvent(name="B", args={})]
    v = diff_call(
        _fix([EmittedEvent(name="A", args={})], []),
        _act(ev_extra, []),
        DiffOptions(),
    )
    assert v.verdict == "FAIL"
    assert v.diff["events"]["extra"] == [{"name": "B", "args": {}}]


def test_event_order_matters():
    ev_expected = [EmittedEvent(name="A", args={}), EmittedEvent(name="B", args={})]
    ev_actual   = [EmittedEvent(name="B", args={}), EmittedEvent(name="A", args={})]
    v = diff_call(_fix(ev_expected, []), _act(ev_actual, []), DiffOptions())
    assert v.verdict == "FAIL"


def test_event_args_normalize_addresses_to_lowercase():
    expected = [EmittedEvent(name="X", args={"who": "0xabcdef"})]
    actual   = [EmittedEvent(name="X", args={"who": "0xABCDEF"})]
    v = diff_call(_fix(expected, []), _act(actual, []), DiffOptions())
    assert v.verdict == "PASS"


def test_missing_state_delta_fails():
    st_expected = [StateDelta(kind="field_set", contract="X", name="q", value="1")]
    v = diff_call(_fix([], st_expected), _act([], []), DiffOptions())
    assert v.verdict == "FAIL"
    assert v.diff["state"]["missing"][0]["name"] == "q"


def test_extra_state_delta_passes_by_default():
    st_expected = [StateDelta(kind="field_set", contract="X", name="q", value="1")]
    st_actual = [
        StateDelta(kind="field_set", contract="X", name="q", value="1"),
        StateDelta(kind="field_set", contract="X", name="extra", value="z"),
    ]
    v = diff_call(_fix([], st_expected), _act([], st_actual), DiffOptions())
    assert v.verdict == "PASS"


def test_extra_state_delta_fails_in_strict_state_superset_mode():
    st_expected = [StateDelta(kind="field_set", contract="X", name="q", value="1")]
    st_actual = [
        StateDelta(kind="field_set", contract="X", name="q", value="1"),
        StateDelta(kind="field_set", contract="X", name="extra", value="z"),
    ]
    v = diff_call(
        _fix([], st_expected), _act([], st_actual),
        DiffOptions(strict_state_superset=True),
    )
    assert v.verdict == "FAIL"


def test_ok_vs_revert_mismatch_fails():
    v = diff_call(_fix(kind="revert", revert="bad"), _act(ok=True), DiffOptions())
    assert v.verdict == "FAIL"
    assert v.diff["result"]["expected"] == "revert"
    assert v.diff["result"]["actual"] == "ok"


def test_revert_reason_ignored_by_default():
    v = diff_call(
        _fix(kind="revert", revert="reason A"),
        _act(ok=False, revert="reason B"),
        DiffOptions(),
    )
    assert v.verdict == "PASS"


def test_strict_reverts_enforces_reason_match():
    v = diff_call(
        _fix(kind="revert", revert="reason A"),
        _act(ok=False, revert="reason B"),
        DiffOptions(strict_reverts=True),
    )
    assert v.verdict == "FAIL"
