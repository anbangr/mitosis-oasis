"""Unit tests for the oracle diff."""

from test.conformance.oracle.diff import DiffOptions, diff_call
from test.conformance.oracle.schema import (
    CallResult, CallResultPayload, EmittedEvent, FixtureCall, StateDelta,
)


def _fix(events=None, state=None, kind="ok", revert=None, return_data=None):
    return FixtureCall(
        idx=0,
        target_contract="X",
        selector="0x0",
        function="f()",
        args=[],
        msg_sender="0x0",
        value_wei="0",
        result=CallResultPayload(
            kind=kind,
            return_data=return_data if return_data is not None else [],
        ),
        events=events or [],
        state_delta=state or [],
        revert_reason=revert,
    )


def _act(events=None, state=None, ok=True, revert=None, return_data=None):
    return CallResult(
        ok=ok, revert=revert,
        events=events or [], state_delta=state or [],
        return_data=return_data,
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


# --- return_data comparison tests (HIGH 1 + HIGH 2) ---

def test_return_data_match_ok():
    """Expected and actual both have the same return_data → PASS."""
    v = diff_call(
        _fix(return_data=["1"]),
        _act(return_data=["1"]),
        DiffOptions(),
    )
    assert v.verdict == "PASS"
    assert v.diff is None


def test_return_data_mismatch_ok_fails():
    """Expected return_data=['1'] but actual=['0'] → FAIL with return_data_mismatch."""
    v = diff_call(
        _fix(return_data=["1"]),
        _act(return_data=["0"]),
        DiffOptions(),
    )
    assert v.verdict == "FAIL"
    assert v.diff is not None
    assert v.diff["result"]["return_data"]["reason"] == "return_data_mismatch"


def test_return_data_missing_in_actual_fails():
    """Expected return_data=['1'] but adapter returned None → FAIL with return_data_missing."""
    v = diff_call(
        _fix(return_data=["1"]),
        _act(return_data=None),
        DiffOptions(),
    )
    assert v.verdict == "FAIL"
    assert v.diff["result"]["return_data"]["reason"] == "return_data_missing"


def test_return_data_absent_in_expected_skipped():
    """Fixture has no return_data assertion (None/[]); adapter returns data → PASS."""
    # empty list default (fixture didn't assert)
    v1 = diff_call(_fix(return_data=[]), _act(return_data=["1"]), DiffOptions())
    assert v1.verdict == "PASS"

    # None explicitly
    v2 = diff_call(_fix(return_data=None), _act(return_data=["1"]), DiffOptions())
    assert v2.verdict == "PASS"


def test_revert_selector_mismatch_fails():
    """Expected revert with custom error selector 0xabcd1234, actual revert returns
    0xdead0000 → FAIL because selectors differ."""
    v = diff_call(
        _fix(kind="revert", return_data="0xabcd1234"),
        _act(ok=False, return_data="0xdead0000"),
        DiffOptions(),
    )
    assert v.verdict == "FAIL"
    assert v.diff["result"]["return_data"]["reason"] == "return_data_mismatch"


def test_revert_selector_match_passes():
    """Same custom error selector on both sides → PASS."""
    v = diff_call(
        _fix(kind="revert", return_data="0xABCD1234"),
        _act(ok=False, return_data="0xabcd1234"),
        DiffOptions(),
    )
    assert v.verdict == "PASS"


# --- state delta multiset tests (MED 6) ---

def test_duplicate_state_delta_counts_must_match():
    """Two identical expected increments vs one actual increment → FAIL.

    The old dict-keyed implementation collapsed duplicates and incorrectly
    reported PASS.  The Counter-based implementation counts correctly.
    """
    dup_delta = StateDelta(kind="counter_inc", contract="X", name="n", delta="1")
    v = diff_call(
        _fix(state=[dup_delta, dup_delta]),
        _act(state=[dup_delta]),
        DiffOptions(),
    )
    assert v.verdict == "FAIL"
    assert v.diff is not None
    assert "state" in v.diff
    assert len(v.diff["state"]["missing"]) == 1


def test_duplicate_state_delta_both_present_passes():
    """Two identical expected increments and two matching actual ones → PASS."""
    dup_delta = StateDelta(kind="counter_inc", contract="X", name="n", delta="1")
    v = diff_call(
        _fix(state=[dup_delta, dup_delta]),
        _act(state=[dup_delta, dup_delta]),
        DiffOptions(),
    )
    assert v.verdict == "PASS"
