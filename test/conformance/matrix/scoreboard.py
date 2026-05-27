"""Scoreboard aggregation for conformance replay verdicts."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping

from test.conformance.oracle.schema import CallVerdict


VERDICTS = ("PASS", "FAIL", "GAP", "ERROR")


def _empty_counts() -> dict[str, int]:
    return {verdict: 0 for verdict in VERDICTS}


def _model_dump(model) -> dict:
    if hasattr(model, "model_dump"):
        return model.model_dump()
    return model.dict()


def _power_for(verdict: CallVerdict, power_map: Mapping[str, str] | None) -> str:
    if power_map and verdict.contract in power_map:
        return power_map[verdict.contract]
    if verdict.power == "legislation":
        return "legislative"
    return verdict.power


@dataclass(frozen=True)
class Scoreboard:
    totals: dict[str, int]
    by_contract: dict[str, dict[str, int]]
    by_power: dict[str, dict[str, int]]
    top_failures: list[dict] = field(default_factory=list)
    top_gaps: list[dict] = field(default_factory=list)

    @property
    def has_error(self) -> bool:
        return self.totals.get("ERROR", 0) > 0

    def to_dict(self) -> dict:
        return {
            "totals": self.totals,
            "by_contract": self.by_contract,
            "by_power": self.by_power,
            "has_error": self.has_error,
            "top_failures": self.top_failures,
            "top_gaps": self.top_gaps,
        }


def aggregate(
    verdicts: list[CallVerdict],
    power_map: Mapping[str, str] | None = None,
    top_n: int = 10,
) -> Scoreboard:
    totals = _empty_counts()
    by_contract: dict[str, dict[str, int]] = {}
    by_power: dict[str, dict[str, int]] = {}
    failures: list[dict] = []
    gaps: list[dict] = []

    for verdict in verdicts:
        totals[verdict.verdict] += 1
        by_contract.setdefault(verdict.contract, _empty_counts())[verdict.verdict] += 1
        by_power.setdefault(_power_for(verdict, power_map), _empty_counts())[
            verdict.verdict
        ] += 1

        if verdict.verdict == "FAIL":
            failures.append(_model_dump(verdict))
        elif verdict.verdict == "GAP":
            gaps.append(_model_dump(verdict))

    return Scoreboard(
        totals=totals,
        by_contract=dict(sorted(by_contract.items())),
        by_power=dict(sorted(by_power.items())),
        top_failures=failures[:top_n],
        top_gaps=gaps[:top_n],
    )
