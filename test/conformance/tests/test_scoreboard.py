"""Tests for the pure conformance scoreboard aggregator."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from test.conformance.matrix.scoreboard import Verdict, aggregate


ZERO_TOTALS = {"PASS": 0, "FAIL": 0, "GAP": 0, "ERROR": 0}


def _verdict(
    verdict: str,
    contract: str,
    function: str,
    fixture_id: str,
    *,
    diff_snippet: str | None = None,
    reason: str | None = None,
) -> Verdict:
    payload = {
        "verdict": verdict,
        "contract": contract,
        "function": function,
        "fixture_id": fixture_id,
    }
    if diff_snippet is not None:
        payload["diff_snippet"] = diff_snippet
    if reason is not None:
        payload["reason"] = reason
    return Verdict(**payload)


def _dump(value):
    if hasattr(value, "model_dump"):
        return value.model_dump()
    if isinstance(value, dict):
        return value
    return vars(value)


def _counts(pass_count: int = 0, fail: int = 0, gap: int = 0, error: int = 0):
    return {"PASS": pass_count, "FAIL": fail, "GAP": gap, "ERROR": error}


def test_empty_input_returns_zeroed_scoreboard():
    scoreboard = aggregate([])

    assert scoreboard.totals == ZERO_TOTALS
    assert scoreboard.has_error is False
    assert scoreboard.by_power == {}
    assert scoreboard.by_contract == {}
    assert scoreboard.by_function == {}
    assert scoreboard.top_failures == []
    assert scoreboard.gaps == []


def test_mixed_verdicts_aggregate_totals_and_error_flag():
    verdicts = [
        *[
            _verdict("PASS", "LegislativePipeline", "fn(uint256)", f"pass-{idx}")
            for idx in range(5)
        ],
        _verdict(
            "FAIL",
            "LegislativePipeline",
            "submitProposal(bytes32)",
            "fail-1",
            diff_snippet="expected ProposalSubmitted event",
        ),
        _verdict(
            "FAIL",
            "VotingVerifier",
            "submitVotingProof(bytes32)",
            "fail-2",
            diff_snippet="expected vote total 60",
        ),
        _verdict(
            "GAP",
            "ConstitutionalReview",
            "hasPassed(uint256)",
            "gap-1",
            reason="adapter not mapped",
        ),
        _verdict(
            "ERROR",
            "GovernanceRegistry",
            "createLaw(bytes32)",
            "error-1",
        ),
    ]

    scoreboard = aggregate(verdicts)

    assert scoreboard.totals == {"PASS": 5, "FAIL": 2, "GAP": 1, "ERROR": 1}
    assert scoreboard.has_error is True


def test_contract_breakdown_sums_to_global_totals():
    verdicts = [
        _verdict("PASS", "ContractA", "alpha()", "a-pass-1"),
        _verdict("PASS", "ContractA", "beta()", "a-pass-2"),
        _verdict(
            "FAIL",
            "ContractA",
            "beta()",
            "a-fail-1",
            diff_snippet="beta mismatch",
        ),
        _verdict("ERROR", "ContractB", "gamma()", "b-error-1"),
        _verdict("PASS", "ContractB", "gamma()", "b-pass-1"),
        _verdict(
            "GAP",
            "ContractC",
            "delta()",
            "c-gap-1",
            reason="no oasis equivalent",
        ),
    ]

    scoreboard = aggregate(verdicts)

    assert set(scoreboard.by_contract) == {"ContractA", "ContractB", "ContractC"}
    assert scoreboard.by_contract["ContractA"] == _counts(pass_count=2, fail=1)
    assert scoreboard.by_contract["ContractB"] == _counts(pass_count=1, error=1)
    assert scoreboard.by_contract["ContractC"] == _counts(gap=1)

    summed = {
        status: sum(counts[status] for counts in scoreboard.by_contract.values())
        for status in ZERO_TOTALS
    }
    assert summed == scoreboard.totals == {"PASS": 3, "FAIL": 1, "GAP": 1, "ERROR": 1}


def test_function_breakdown_keeps_functions_of_same_contract_distinct():
    verdicts = [
        _verdict("PASS", "ContractA", "fn1()", "fn1-pass-1"),
        _verdict("PASS", "ContractA", "fn1()", "fn1-pass-2"),
        _verdict(
            "FAIL",
            "ContractA",
            "fn2(uint256)",
            "fn2-fail-1",
            diff_snippet="wrong return value",
        ),
        _verdict(
            "GAP",
            "ContractA",
            "fn2(uint256)",
            "fn2-gap-1",
            reason="event capture missing",
        ),
    ]

    scoreboard = aggregate(verdicts)

    assert scoreboard.by_function["ContractA.fn1()"] == _counts(pass_count=2)
    assert scoreboard.by_function["ContractA.fn2(uint256)"] == _counts(
        fail=1,
        gap=1,
    )
    assert scoreboard.by_function["ContractA.fn1()"] != scoreboard.by_function[
        "ContractA.fn2(uint256)"
    ]


def test_by_power_rolls_contracts_into_supplied_power_map():
    verdicts = [
        _verdict("PASS", "ContractA", "alpha()", "a-pass-1"),
        _verdict(
            "FAIL",
            "ContractA",
            "alpha()",
            "a-fail-1",
            diff_snippet="alpha mismatch",
        ),
        _verdict("PASS", "ContractB", "beta()", "b-pass-1"),
        _verdict("ERROR", "ContractB", "beta()", "b-error-1"),
    ]

    scoreboard = aggregate(
        verdicts,
        power_map={"ContractA": "legislative", "ContractB": "legislative"},
    )

    assert scoreboard.by_power == {
        "legislative": {"PASS": 2, "FAIL": 1, "GAP": 0, "ERROR": 1}
    }


def test_power_map_none_leaves_power_rollup_empty():
    scoreboard = aggregate(
        [
            _verdict("PASS", "ContractA", "alpha()", "a-pass-1"),
            _verdict("ERROR", "ContractB", "beta()", "b-error-1"),
        ],
        power_map=None,
    )

    assert scoreboard.by_power == {}


def test_unmapped_contracts_with_supplied_power_map_accumulate_as_unknown():
    verdicts = [
        _verdict("PASS", "ContractA", "alpha()", "a-pass-1"),
        _verdict("PASS", "ContractB", "beta()", "b-pass-1"),
        _verdict(
            "FAIL",
            "ContractB",
            "beta()",
            "b-fail-1",
            diff_snippet="beta mismatch",
        ),
    ]

    scoreboard = aggregate(verdicts, power_map={"ContractA": "legislative"})

    assert scoreboard.by_power["legislative"] == _counts(pass_count=1)
    assert scoreboard.by_power["unknown"] == _counts(pass_count=1, fail=1)


def test_top_failures_returns_deterministic_top_n_records_with_truncated_diffs():
    long_diff = "diff:" + ("x" * 400)
    verdicts = [
        _verdict(
            "FAIL",
            f"Contract{contract}",
            f"fn{function}()",
            f"fixture-{idx:02d}",
            diff_snippet=long_diff if idx == 7 else f"diff-{idx}",
        )
        for idx, (contract, function) in enumerate(
            [
                ("C", "zeta"),
                ("A", "beta"),
                ("B", "alpha"),
                ("A", "alpha"),
                ("C", "alpha"),
                ("B", "beta"),
                ("A", "gamma"),
                ("A", "alpha"),
                ("D", "omega"),
                ("B", "delta"),
                ("C", "beta"),
                ("A", "delta"),
            ]
        )
    ]

    scoreboard = aggregate(verdicts, top_n=5)
    failures = [_dump(record) for record in scoreboard.top_failures]

    expected_sorted = sorted(
        (
            (verdict.contract, verdict.function, verdict.fixture_id)
            for verdict in verdicts
        )
    )[:5]
    assert len(failures) == 5
    assert [
        (record["contract"], record["function"], record["fixture_id"])
        for record in failures
    ] == expected_sorted
    assert all(
        {"contract", "function", "fixture_id", "diff_snippet"} <= set(record)
        for record in failures
    )
    long_failure = next(record for record in failures if record["fixture_id"] == "fixture-07")
    assert long_failure["diff_snippet"].startswith("diff:")
    assert len(long_failure["diff_snippet"]) <= 280


def test_gaps_list_one_record_per_unmapped_contract_function_reason():
    verdicts = [
        _verdict(
            "GAP",
            "ContractB",
            "beta()",
            "gap-1",
            reason="missing adapter",
        ),
        _verdict(
            "GAP",
            "ContractA",
            "gamma()",
            "gap-2",
            reason="no matching oasis function",
        ),
        _verdict(
            "GAP",
            "ContractA",
            "alpha()",
            "gap-3",
            reason="event not captured",
        ),
        _verdict(
            "GAP",
            "ContractA",
            "alpha()",
            "gap-4",
            reason="state view missing",
        ),
    ]

    scoreboard = aggregate(verdicts)
    gaps = [_dump(record) for record in scoreboard.gaps]

    assert gaps == [
        {
            "contract": "ContractA",
            "function": "alpha()",
            "reason": "event not captured",
        },
        {
            "contract": "ContractA",
            "function": "alpha()",
            "reason": "state view missing",
        },
        {
            "contract": "ContractA",
            "function": "gamma()",
            "reason": "no matching oasis function",
        },
        {
            "contract": "ContractB",
            "function": "beta()",
            "reason": "missing adapter",
        },
    ]


def test_identical_contract_function_verdicts_accumulate_without_overwrite():
    verdicts = [
        _verdict("PASS", "ContractA", "alpha()", "a-pass-1"),
        _verdict("PASS", "ContractA", "alpha()", "a-pass-2"),
        _verdict(
            "FAIL",
            "ContractA",
            "alpha()",
            "a-fail-1",
            diff_snippet="first mismatch",
        ),
        _verdict(
            "FAIL",
            "ContractA",
            "alpha()",
            "a-fail-2",
            diff_snippet="second mismatch",
        ),
    ]

    scoreboard = aggregate(verdicts)

    assert scoreboard.by_contract["ContractA"] == _counts(pass_count=2, fail=2)
    assert scoreboard.by_function["ContractA.alpha()"] == _counts(pass_count=2, fail=2)


def test_unknown_verdict_value_raises_value_error():
    malformed = SimpleNamespace(
        verdict="SKIP",
        contract="ContractA",
        function="alpha()",
        fixture_id="unknown-1",
    )

    with pytest.raises(ValueError):
        aggregate([malformed])


def test_aggregate_is_deterministic_for_same_input():
    verdicts = [
        _verdict(
            "FAIL",
            "ContractB",
            "beta()",
            "fail-2",
            diff_snippet="beta mismatch",
        ),
        _verdict("PASS", "ContractA", "alpha()", "pass-1"),
        _verdict(
            "GAP",
            "ContractA",
            "gamma()",
            "gap-1",
            reason="missing adapter",
        ),
        _verdict(
            "FAIL",
            "ContractA",
            "alpha()",
            "fail-1",
            diff_snippet="alpha mismatch",
        ),
    ]

    first = aggregate(verdicts, power_map={"ContractA": "legislative"}, top_n=10)
    second = aggregate(verdicts, power_map={"ContractA": "legislative"}, top_n=10)

    assert first == second
    assert [_dump(record) for record in first.top_failures] == [
        _dump(record) for record in second.top_failures
    ]
