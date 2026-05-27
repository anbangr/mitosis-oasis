"""Pure aggregation helpers for conformance replay verdicts."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from pydantic import BaseModel, ConfigDict


class Verdict(BaseModel):
    """Minimal per-call verdict shape consumed by the scoreboard."""

    model_config = ConfigDict(extra="forbid")

    verdict: str
    contract: str
    function: str
    fixture_id: str
    diff_snippet: str | None = None
    reason: str | None = None


class FailureRecord(BaseModel):
    """Compact FAIL payload for reports and human triage."""

    model_config = ConfigDict(extra="forbid")

    contract: str
    function: str
    fixture_id: str
    diff_snippet: str


class GapRecord(BaseModel):
    """Compact GAP payload for report generation."""

    model_config = ConfigDict(extra="forbid")

    contract: str
    function: str
    reason: str


class Scoreboard(BaseModel):
    """Aggregated conformance verdict rollups."""

    model_config = ConfigDict(extra="forbid")

    totals: dict[str, int]
    has_error: bool
    by_power: dict[str, dict[str, int]]
    by_contract: dict[str, dict[str, int]]
    by_function: dict[str, dict[str, int]]
    top_failures: list[FailureRecord]
    gaps: list[GapRecord]


def aggregate(
    verdicts: list[Verdict],
    *,
    power_map: dict[str, str] | None = None,
    top_n: int = 10,
) -> Scoreboard:
    """Roll up per-call verdicts into a JSON-friendly scoreboard."""

    statuses = ("PASS", "FAIL", "GAP", "ERROR")
    totals = _zero_counts(statuses)
    by_contract: dict[str, dict[str, int]] = {}
    by_function: dict[str, dict[str, int]] = {}
    by_power: dict[str, dict[str, int]] = {}
    failures: list[FailureRecord] = []
    gaps: list[GapRecord] = []
    gap_keys: set[tuple[str, str, str]] = set()

    for verdict in verdicts:
        status = str(_field(verdict, "verdict"))
        if status not in statuses:
            raise ValueError(f"unknown verdict value: {status}")

        contract = str(_field(verdict, "contract"))
        function = str(_field(verdict, "function"))
        fixture_id = str(_field(verdict, "fixture_id"))

        totals[status] += 1
        _increment(by_contract, contract, status, statuses)
        _increment(by_function, f"{contract}.{function}", status, statuses)

        if power_map is not None:
            power = power_map.get(contract, "unknown")
            _increment(by_power, power, status, statuses)

        if status == "FAIL":
            failures.append(
                FailureRecord(
                    contract=contract,
                    function=function,
                    fixture_id=fixture_id,
                    diff_snippet=_truncate(_diff_snippet(verdict)),
                )
            )
        elif status == "GAP":
            reason = _gap_reason(verdict)
            key = (contract, function, reason)
            if key not in gap_keys:
                gap_keys.add(key)
                gaps.append(
                    GapRecord(contract=contract, function=function, reason=reason)
                )

    return Scoreboard(
        totals=totals,
        has_error=totals["ERROR"] > 0,
        by_power=_sorted_counts(by_power),
        by_contract=_sorted_counts(by_contract),
        by_function=_sorted_counts(by_function),
        top_failures=sorted(
            failures,
            key=lambda record: (record.contract, record.function, record.fixture_id),
        )[: max(top_n, 0)],
        gaps=sorted(gaps, key=lambda record: (record.contract, record.function)),
    )


def _zero_counts(statuses: Iterable[str]) -> dict[str, int]:
    return {status: 0 for status in statuses}


def _increment(
    rollup: dict[str, dict[str, int]],
    key: str,
    status: str,
    statuses: Iterable[str],
) -> None:
    if key not in rollup:
        rollup[key] = _zero_counts(statuses)
    rollup[key][status] += 1


def _sorted_counts(rollup: dict[str, dict[str, int]]) -> dict[str, dict[str, int]]:
    return {key: rollup[key] for key in sorted(rollup)}


def _field(verdict: Any, name: str) -> Any:
    if isinstance(verdict, dict):
        return verdict[name]
    return getattr(verdict, name)


def _diff_snippet(verdict: Any) -> str:
    snippet = _optional_field(verdict, "diff_snippet")
    if snippet is not None:
        return str(snippet)

    diff = _optional_field(verdict, "diff")
    if diff is not None:
        return str(diff)

    return ""


def _gap_reason(verdict: Any) -> str:
    reason = _optional_field(verdict, "reason")
    if reason is not None:
        return str(reason)

    error = _optional_field(verdict, "error")
    if error is not None:
        text = str(error)
        return text[5:] if text.startswith("GAP: ") else text

    return ""


def _optional_field(verdict: Any, name: str) -> Any:
    if isinstance(verdict, dict):
        return verdict.get(name)
    return getattr(verdict, name, None)


def _truncate(value: str, limit: int = 280) -> str:
    if len(value) <= limit:
        return value
    return value[:limit]
