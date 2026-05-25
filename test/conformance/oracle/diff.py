"""Pure-function diff between an expected FixtureCall and an actual CallResult.

Per spec §10 default: strict event-set equality (extra event = FAIL).
Per spec §5  default: extras in state delta are allowed; flippable.
Per spec §5  default: revert reason ignored; flippable.
"""

from __future__ import annotations

from dataclasses import dataclass

from test.conformance.oracle.schema import (
    CallResult, CallVerdict, EmittedEvent, FixtureCall, Power, StateDelta,
)


@dataclass(frozen=True)
class DiffOptions:
    strict_event_set: bool = True          # extras in actual events → FAIL
    strict_state_superset: bool = False    # extras in actual state → FAIL when True
    strict_reverts: bool = False           # match revert reason string


# ---------- normalization ----------

def _norm_value(v):
    if isinstance(v, str):
        if v.startswith("0x") or v.startswith("0X"):
            return v.lower()
        return v
    if isinstance(v, dict):
        return {k: _norm_value(x) for k, x in v.items()}
    if isinstance(v, list):
        return [_norm_value(x) for x in v]
    return v


def _norm_event(e: EmittedEvent) -> dict:
    return {"name": e.name, "args": {k: _norm_value(v) for k, v in e.args.items()}}


def _norm_state(s: StateDelta) -> tuple:
    """Hashable key: every StateDelta is uniquely identified by these fields."""
    return (s.kind, s.contract, s.name,
            _norm_value(s.key) if s.key is not None else None,
            _norm_value(s.value) if s.value is not None else None,
            _norm_value(s.delta) if s.delta is not None else None)


# ---------- diff stages ----------

def _diff_events(expected: list[EmittedEvent], actual: list[EmittedEvent],
                 opts: DiffOptions) -> dict | None:
    exp = [_norm_event(e) for e in expected]
    act = [_norm_event(e) for e in actual]

    # 1. expected must appear in the same order as a prefix-respecting subsequence
    #    (strictly: positions must match because Solidity emits deterministically)
    if exp != act[: len(exp)]:
        return {"expected": exp, "actual": act, "reason": "sequence_mismatch"}

    # 2. extras: allowed unless strict_event_set
    if opts.strict_event_set and len(act) > len(exp):
        return {"expected": exp, "actual": act,
                "extra": act[len(exp):], "reason": "unexpected_extra_event"}
    return None


def _diff_state(expected: list[StateDelta], actual: list[StateDelta],
                opts: DiffOptions) -> dict | None:
    exp = {_norm_state(s): s.model_dump() for s in expected}
    act = {_norm_state(s): s.model_dump() for s in actual}

    missing = [v for k, v in exp.items() if k not in act]
    extra   = [v for k, v in act.items() if k not in exp]

    if missing:
        return {"missing": missing, "extra": extra, "reason": "state_missing"}
    if extra and opts.strict_state_superset:
        return {"missing": [], "extra": extra, "reason": "state_extra"}
    return None


def _diff_result(expected_kind: str, expected_revert: str | None,
                 actual_ok: bool, actual_revert: str | None,
                 opts: DiffOptions) -> dict | None:
    actual_kind = "ok" if actual_ok else "revert"
    if expected_kind != actual_kind:
        return {"expected": expected_kind, "actual": actual_kind,
                "reason": "result_kind_mismatch"}
    if expected_kind == "revert" and opts.strict_reverts:
        if (expected_revert or "") != (actual_revert or ""):
            return {"expected_revert": expected_revert, "actual_revert": actual_revert,
                    "reason": "revert_reason_mismatch"}
    return None


# ---------- public API ----------

def diff_call(expected: FixtureCall, actual: CallResult,
              opts: DiffOptions,
              fixture_id: str = "unknown",
              power: Power = "legislation") -> CallVerdict:
    diff: dict = {}

    r = _diff_result(expected.result.kind, expected.revert_reason,
                     actual.ok, actual.revert, opts)
    if r is not None:
        diff["result"] = r

    e = _diff_events(expected.events, actual.events, opts)
    if e is not None:
        diff["events"] = e

    s = _diff_state(expected.state_delta, actual.state_delta, opts)
    if s is not None:
        diff["state"] = s

    verdict = "PASS" if not diff else "FAIL"
    return CallVerdict(
        verdict=verdict,
        fixture_id=fixture_id,
        call_idx=expected.idx,
        contract=expected.target_contract,
        function=expected.function,
        power=power,
        diff=diff or None,
    )
