"""Tests for the deterministic conformance report writer."""

from __future__ import annotations

import copy
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest


@dataclass(frozen=True)
class HandBuiltScoreboard:
    totals: dict[str, int]
    has_error: bool
    by_power: dict[str, dict[str, int]]
    by_contract: dict[str, dict[str, int]]
    by_function: dict[str, dict[str, int]]
    top_failures: list[dict[str, str]]
    gaps: list[dict[str, str]]

    def model_dump(self) -> dict[str, Any]:
        return copy.deepcopy(
            {
                "totals": self.totals,
                "has_error": self.has_error,
                "by_power": self.by_power,
                "by_contract": self.by_contract,
                "by_function": self.by_function,
                "top_failures": self.top_failures,
                "gaps": self.gaps,
            }
        )


def _counts(pass_count: int = 0, fail: int = 0, gap: int = 0, error: int = 0):
    return {"PASS": pass_count, "FAIL": fail, "GAP": gap, "ERROR": error}


def _mixed_scoreboard() -> HandBuiltScoreboard:
    long_contract = (
        "ExtremelyLongConformanceContractNameThatShouldRemainVisibleInMarkdownTables"
    )
    return HandBuiltScoreboard(
        totals=_counts(pass_count=5, fail=3, gap=2, error=1),
        has_error=True,
        by_power={
            "legislative": _counts(pass_count=5, fail=2, gap=1, error=0),
            "judicial": _counts(pass_count=0, fail=1, gap=1, error=1),
        },
        by_contract={
            "GovernanceRegistry": _counts(pass_count=4, fail=1, gap=0, error=0),
            long_contract: _counts(pass_count=1, fail=2, gap=2, error=1),
        },
        by_function={
            "GovernanceRegistry.getLaw(bytes32)": _counts(pass_count=4),
            "GovernanceRegistry.registerLaw(bytes32)": _counts(fail=1),
            f"{long_contract}.verifyDeployment(bytes32)": _counts(fail=2, gap=1),
            f"{long_contract}.simulateError()": _counts(error=1),
        },
        top_failures=[
            {
                "contract": "GovernanceRegistry",
                "function": "registerLaw(bytes32)",
                "fixture_id": "fixture-a",
                "diff_snippet": "expected law id 0xabc but got 0xdef",
            },
            {
                "contract": long_contract,
                "function": "verifyDeployment(bytes32)",
                "fixture_id": "fixture-b",
                "diff_snippet": "missing LawRegistered event",
            },
            {
                "contract": long_contract,
                "function": "verifyDeployment(bytes32)",
                "fixture_id": "fixture-c",
                "diff_snippet": "return_data[0] mismatch",
            },
        ],
        gaps=[
            {
                "contract": long_contract,
                "function": "verifyDeployment(bytes32)",
                "fixture_id": "fixture-gap-1",
                "reason": "adapter has no oasis entrypoint",
            },
            {
                "contract": "ConstitutionalReview",
                "function": "reviewProposal(uint256)",
                "fixture_id": "fixture-gap-2",
                "reason": "fixture requires unsupported calldata shape",
            },
        ],
    )


def _scoreboard_with_totals(
    totals: dict[str, int],
    *,
    has_error: bool = False,
    by_power: dict[str, dict[str, int]] | None = None,
) -> HandBuiltScoreboard:
    return HandBuiltScoreboard(
        totals=totals,
        has_error=has_error,
        by_power=by_power if by_power is not None else {"legislative": totals},
        by_contract={"LegislativePipeline": totals},
        by_function={"LegislativePipeline.submitProposal(bytes32)": totals},
        top_failures=[],
        gaps=[],
    )


def _write_report(scoreboard: HandBuiltScoreboard, tmp_path: Path, **kwargs: Any):
    from test.conformance.matrix.report import write_report

    options = {
        "contracts_sha": "deadbeef",
        "run_id": "r1",
        "fixture_count": 3,
        "call_count": 12,
        "out_root": tmp_path / "nested" / "reports",
        "pass_threshold": 0.95,
    }
    options.update(kwargs)
    return write_report(scoreboard, **options)


def _rendered_paths(
    scoreboard: HandBuiltScoreboard, tmp_path: Path, **kwargs: Any
) -> tuple[Path, Path]:
    contracts_sha = kwargs.get("contracts_sha", "deadbeef")
    out_root = kwargs.get("out_root", tmp_path / "nested" / "reports")
    _write_report(scoreboard, tmp_path, **kwargs)
    out_dir = out_root / contracts_sha
    return out_dir / "conformance.md", out_dir / "conformance.json"


def test_write_report_creates_markdown_and_json_under_contracts_sha(tmp_path: Path):
    md_path, json_path = _rendered_paths(_mixed_scoreboard(), tmp_path)

    assert md_path.exists()
    assert json_path.exists()


def test_conformance_json_round_trips_metadata_and_scoreboard(tmp_path: Path):
    scoreboard = _mixed_scoreboard()
    _, json_path = _rendered_paths(scoreboard, tmp_path)

    payload = json.loads(json_path.read_text())

    assert payload == {
        "metadata": {
            "contracts_sha": "deadbeef",
            "run_id": "r1",
            "fixture_count": 3,
            "call_count": 12,
            "pass_threshold": 0.95,
        },
        "scoreboard": scoreboard.model_dump(),
    }


@pytest.mark.parametrize(
    ("scoreboard", "fixture_count", "expected_verdict"),
    [
        (_scoreboard_with_totals(_counts(pass_count=19, gap=1)), 20, "PASS"),
        (_scoreboard_with_totals(_counts(pass_count=14, fail=5, gap=1)), 20, "FAIL"),
        (
            _scoreboard_with_totals(_counts(pass_count=19, error=1), has_error=True),
            20,
            "FAIL",
        ),
        (_scoreboard_with_totals(_counts(), by_power={}), 0, "NO_DATA"),
    ],
)
def test_markdown_overall_verdict_follows_phase_1_gate(
    tmp_path: Path,
    scoreboard: HandBuiltScoreboard,
    fixture_count: int,
    expected_verdict: str,
):
    md_path, _ = _rendered_paths(scoreboard, tmp_path, fixture_count=fixture_count)

    assert f"Overall verdict: {expected_verdict}" in md_path.read_text()


def test_markdown_surfaces_metadata_power_contract_and_function_sections(
    tmp_path: Path,
):
    scoreboard = _mixed_scoreboard()
    md_path, _ = _rendered_paths(scoreboard, tmp_path)

    body = md_path.read_text()

    assert "contracts_sha" in body
    assert "deadbeef" in body
    assert "run_id" in body
    assert "r1" in body
    assert "fixture_count" in body
    assert "3" in body
    assert "call_count" in body
    assert "12" in body
    assert re.search(
        r"legislative.*\b5\b.*\b2\b.*\b1\b.*\b0\b",
        body,
        flags=re.IGNORECASE | re.DOTALL,
    )
    assert "GovernanceRegistry" in body
    assert "ExtremelyLongConformanceContractNameThatShouldRemainVisibleInMarkdownTables" in body
    assert "GovernanceRegistry.registerLaw(bytes32)" in body
    assert "verifyDeployment(bytes32)" in body
    assert "simulateError()" in body
    assert "GovernanceRegistry.getLaw(bytes32)" not in body


def test_markdown_lists_all_top_failures_and_gaps(tmp_path: Path):
    md_path, _ = _rendered_paths(_mixed_scoreboard(), tmp_path)

    body = md_path.read_text()

    assert "Top FAILures" in body
    for failure in _mixed_scoreboard().top_failures:
        assert failure["contract"] in body
        assert failure["function"] in body
        assert failure["fixture_id"] in body
        assert failure["diff_snippet"] in body
    assert "GAPs" in body
    for gap in _mixed_scoreboard().gaps:
        assert gap["contract"] in body
        assert gap["function"] in body
        assert gap["fixture_id"] in body
        assert gap["reason"] in body


def test_write_report_is_byte_identical_when_written_twice(tmp_path: Path):
    scoreboard = _mixed_scoreboard()
    md_path, json_path = _rendered_paths(scoreboard, tmp_path)
    first_md = md_path.read_bytes()
    first_json = json_path.read_bytes()

    _write_report(scoreboard, tmp_path)

    assert md_path.read_bytes() == first_md
    assert json_path.read_bytes() == first_json


def test_per_power_gate_shows_non_gap_pass_percent_and_marker(tmp_path: Path):
    scoreboard = _scoreboard_with_totals(
        _counts(pass_count=19, gap=1),
        by_power={"legislative": _counts(pass_count=19, gap=1)},
    )

    md_path, _ = _rendered_paths(scoreboard, tmp_path, fixture_count=20)

    assert re.search(
        r"legislative.*100(?:\.0+)?%.*PASS",
        md_path.read_text(),
        flags=re.IGNORECASE | re.DOTALL,
    )


def test_empty_scoreboard_renders_no_data_and_diff_friendly_placeholders(
    tmp_path: Path,
):
    scoreboard = _scoreboard_with_totals(_counts(), by_power={})

    md_path, _ = _rendered_paths(scoreboard, tmp_path, fixture_count=0, call_count=0)

    body = md_path.read_text()
    assert "Overall verdict: NO_DATA" in body
    assert "Top FAILures" in body
    assert "_(none)_" in body
    assert "GAPs" in body
    assert "_(no power_map supplied)_" in body
