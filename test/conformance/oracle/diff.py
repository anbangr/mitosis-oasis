"""Pure-function diff between an expected FixtureCall and an actual CallResult.

Per spec §10 default: strict event-set equality (extra event = FAIL).
Per spec §5  default: extras in state delta are allowed; flippable.
Per spec §5  default: revert reason ignored; flippable.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass

from test.conformance.oracle.schema import (
    CallResult,
    CallVerdict,
    EmittedEvent,
    FixtureCall,
    Power,
    StateDelta,
)


@dataclass(frozen=True)
class DiffOptions:
    strict_event_set: bool = True  # extras in actual events → FAIL
    strict_state_superset: bool = False  # extras in actual state → FAIL when True
    strict_reverts: bool = False  # match revert reason string


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
    return (
        s.kind,
        s.contract,
        s.name,
        _norm_value(s.key) if s.key is not None else None,
        _norm_value(s.value) if s.value is not None else None,
        _norm_value(s.delta) if s.delta is not None else None,
    )


# ---------- diff stages ----------


def _diff_events(
    expected: list[EmittedEvent], actual: list[EmittedEvent], opts: DiffOptions
) -> dict | None:
    exp = [_norm_event(e) for e in expected]
    act = [_norm_event(e) for e in actual]

    # 1. expected must appear in the same order as a prefix-respecting subsequence
    #    (strictly: positions must match because Solidity emits deterministically)
    if exp != act[: len(exp)]:
        return {"expected": exp, "actual": act, "reason": "sequence_mismatch"}

    # 2. extras: allowed unless strict_event_set
    if opts.strict_event_set and len(act) > len(exp):
        return {
            "expected": exp,
            "actual": act,
            "extra": act[len(exp) :],
            "reason": "unexpected_extra_event",
        }
    return None


def _diff_state(
    expected: list[StateDelta], actual: list[StateDelta], opts: DiffOptions
) -> dict | None:
    # Use Counter (multiset) so that two identical expected deltas are counted
    # separately — a single matching actual cannot satisfy both.
    exp_counts = Counter(_norm_state(s) for s in expected)
    act_counts = Counter(_norm_state(s) for s in actual)

    # Counter subtraction keeps only positive counts.
    missing_counts = exp_counts - act_counts
    extra_counts = act_counts - exp_counts

    # Reconstruct human-readable dicts by finding representative model_dump()
    # values for each key (order may vary, so build a lookup once).
    exp_by_key = {_norm_state(s): s.model_dump() for s in expected}
    act_by_key = {_norm_state(s): s.model_dump() for s in actual}

    missing = [exp_by_key[k] for k, cnt in missing_counts.items() for _ in range(cnt)]
    extra = [act_by_key[k] for k, cnt in extra_counts.items() for _ in range(cnt)]

    if missing:
        return {"missing": missing, "extra": extra, "reason": "state_missing"}
    if extra and opts.strict_state_superset:
        return {"missing": [], "extra": extra, "reason": "state_extra"}
    return None


def _norm_return_data(rd) -> list[str] | str | None:
    """Normalise return_data to a comparable form (lowercase hex strings)."""
    if rd is None:
        return None
    if isinstance(rd, list):
        return [
            _norm_value(x)
            if not isinstance(x, str)
            else (x.lower() if x.startswith(("0x", "0X")) else x)
            for x in rd
        ]
    # str — raw ABI-encoded hex
    if isinstance(rd, str):
        return rd.lower() if rd.startswith(("0x", "0X")) else rd
    return rd


def _diff_return_data(expected_rd, actual_rd) -> dict | None:
    """Compare return_data from expected fixture vs actual CallResult.

    Rules:
    - Both None  → no assertion needed (PASS).
    - Expected None, actual present → fixture didn't capture; skip (PASS).
    - Expected present, actual None → data missing from adapter (FAIL).
    - Both present → normalise and compare; mismatch → FAIL.
    """
    if expected_rd is None:
        return None  # fixture chose not to assert on return data
    if actual_rd is None:
        return {
            "expected": expected_rd,
            "actual": None,
            "reason": "return_data_missing",
        }
    norm_exp = _norm_return_data(expected_rd)
    norm_act = _norm_return_data(actual_rd)
    if norm_exp != norm_act:
        return {
            "expected": expected_rd,
            "actual": actual_rd,
            "reason": "return_data_mismatch",
        }
    return None


def _diff_result(
    expected_kind: str,
    expected_revert: str | None,
    actual_ok: bool,
    actual_revert: str | None,
    opts: DiffOptions,
) -> dict | None:
    actual_kind = "ok" if actual_ok else "revert"
    if expected_kind != actual_kind:
        return {
            "expected": expected_kind,
            "actual": actual_kind,
            "reason": "result_kind_mismatch",
        }
    if expected_kind == "revert" and opts.strict_reverts:
        if (expected_revert or "") != (actual_revert or ""):
            return {
                "expected_revert": expected_revert,
                "actual_revert": actual_revert,
                "reason": "revert_reason_mismatch",
            }
    return None


# ---------- public API ----------


def diff_call(
    expected: FixtureCall,
    actual: CallResult,
    opts: DiffOptions,
    fixture_id: str = "unknown",
    power: Power = "legislation",
) -> CallVerdict:
    diff: dict = {}

    r = _diff_result(
        expected.result.kind, expected.revert_reason, actual.ok, actual.revert, opts
    )
    if r is not None:
        diff["result"] = r
    else:
        # kinds match — now compare return_data
        # For ok results: compare decoded return values.
        # For revert results: when revert_reason is None the fixture may store
        # the custom-error ABI selector in return_data instead; compare that.
        exp_rd = (
            expected.result.return_data if expected.result.return_data != [] else None
        )
        # Treat empty list [] as "no assertion" (many fixtures use it as default).
        # Treat "0x" (empty bytes) as "no assertion" for ok calls.
        if isinstance(exp_rd, str) and exp_rd in ("0x", "0X", ""):
            exp_rd = None
        rd = _diff_return_data(exp_rd, actual.return_data)
        if rd is not None:
            diff.setdefault("result", {})["return_data"] = rd

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
