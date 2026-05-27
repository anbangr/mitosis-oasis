"""Deterministic markdown and JSON report writer for conformance scoreboards."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Protocol


STATUSES = ("PASS", "FAIL", "GAP", "ERROR")


class Scoreboard(Protocol):
    """Minimal report-facing shape shared by pydantic models and test doubles."""

    def model_dump(self) -> dict[str, Any]:
        """Return the JSON-ready scoreboard payload."""


def write_report(
    scoreboard: Scoreboard,
    *,
    contracts_sha: str,
    run_id: str,
    fixture_count: int,
    call_count: int,
    out_root: Path,
    pass_threshold: float = 0.95,
) -> Path:
    """Write conformance.md and conformance.json under out_root/contracts_sha."""

    out_dir = out_root / contracts_sha
    out_dir.mkdir(parents=True, exist_ok=True)

    scoreboard_payload = _model_dump(scoreboard)
    metadata = {
        "contracts_sha": contracts_sha,
        "run_id": run_id,
        "fixture_count": fixture_count,
        "call_count": call_count,
        "pass_threshold": pass_threshold,
    }
    payload = {"metadata": metadata, "scoreboard": scoreboard_payload}

    md_path = out_dir / "conformance.md"
    json_path = out_dir / "conformance.json"

    md_path.write_text(
        _render_markdown(
            metadata=metadata,
            scoreboard=scoreboard_payload,
            pass_threshold=pass_threshold,
        )
    )
    json_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n"
    )

    return out_dir


def _model_dump(scoreboard: Scoreboard) -> dict[str, Any]:
    try:
        return scoreboard.model_dump(mode="json")  # type: ignore[call-arg]
    except TypeError:
        return scoreboard.model_dump()


def _render_markdown(
    *,
    metadata: dict[str, Any],
    scoreboard: dict[str, Any],
    pass_threshold: float,
) -> str:
    lines = [
        "# Conformance Report",
        "",
        "## Metadata",
        "",
        f"- contracts_sha: {metadata['contracts_sha']}",
        f"- run_id: {metadata['run_id']}",
        f"- fixture_count: {metadata['fixture_count']}",
        f"- call_count: {metadata['call_count']}",
        f"- pass_threshold: {metadata['pass_threshold']}",
        "",
        "## Per-Power Gate",
        "",
    ]
    lines.extend(_render_power_rows(scoreboard.get("by_power", {}), pass_threshold))
    lines.extend(
        [
            "",
            "## Per-Contract Results",
            "",
            "| Contract | PASS | FAIL | GAP | ERROR |",
            "| --- | ---: | ---: | ---: | ---: |",
        ]
    )
    lines.extend(_render_count_rows(scoreboard.get("by_contract", {}), "Contract"))
    lines.extend(
        [
            "",
            "## Per-Function Non-PASS Results",
            "",
            "| Function | PASS | FAIL | GAP | ERROR |",
            "| --- | ---: | ---: | ---: | ---: |",
        ]
    )
    lines.extend(_render_function_rows(scoreboard.get("by_function", {})))
    lines.extend(["", "## Top FAILures", ""])
    lines.extend(_render_top_failures(scoreboard.get("top_failures", [])))
    lines.extend(["", "## GAPs", ""])
    lines.extend(_render_gaps(scoreboard.get("gaps", [])))
    lines.extend(
        [
            "",
            f"Overall verdict: {_overall_verdict(scoreboard, metadata['fixture_count'], pass_threshold)}",
            "",
        ]
    )
    return "\n".join(lines)


def _render_power_rows(
    by_power: dict[str, dict[str, int]], pass_threshold: float
) -> list[str]:
    if not by_power:
        return ["_(no power_map supplied)_"]

    rows = [
        "| Power | PASS | FAIL | GAP | ERROR | non-GAP PASS% | Gate |",
        "| --- | ---: | ---: | ---: | ---: | ---: | --- |",
    ]
    for power, counts in sorted(by_power.items()):
        rows.append(
            "| "
            f"{power} | "
            f"{_count(counts, 'PASS')} | "
            f"{_count(counts, 'FAIL')} | "
            f"{_count(counts, 'GAP')} | "
            f"{_count(counts, 'ERROR')} | "
            f"{_format_percent(_non_gap_pass_rate(counts))} | "
            f"{_gate_marker(counts, pass_threshold)} |"
        )
    return rows


def _render_count_rows(
    count_map: dict[str, dict[str, int]], label: str
) -> list[str]:
    if not count_map:
        return [f"| _(no {label.lower()} rows)_ | 0 | 0 | 0 | 0 |"]

    return [
        "| "
        f"{name} | "
        f"{_count(counts, 'PASS')} | "
        f"{_count(counts, 'FAIL')} | "
        f"{_count(counts, 'GAP')} | "
        f"{_count(counts, 'ERROR')} |"
        for name, counts in sorted(count_map.items())
    ]


def _render_function_rows(by_function: dict[str, dict[str, int]]) -> list[str]:
    rows = []
    for name, counts in sorted(by_function.items()):
        if all(_count(counts, status) == 0 for status in ("FAIL", "GAP", "ERROR")):
            continue
        rows.append(
            "| "
            f"{name} | "
            f"{_count(counts, 'PASS')} | "
            f"{_count(counts, 'FAIL')} | "
            f"{_count(counts, 'GAP')} | "
            f"{_count(counts, 'ERROR')} |"
        )
    return rows or ["| _(none)_ | 0 | 0 | 0 | 0 |"]


def _render_top_failures(top_failures: list[dict[str, str]]) -> list[str]:
    if not top_failures:
        return ["_(none)_"]

    rows = []
    for failure in top_failures:
        rows.append(
            "- "
            f"{failure.get('contract', '')}."
            f"{failure.get('function', '')} "
            f"[{failure.get('fixture_id', '')}]: "
            f"{failure.get('diff_snippet', '')}"
        )
    return rows


def _render_gaps(gaps: list[dict[str, str]]) -> list[str]:
    if not gaps:
        return ["_(none)_"]

    rows = []
    for gap in gaps:
        rows.append(
            "- "
            f"{gap.get('contract', '')}."
            f"{gap.get('function', '')} "
            f"[{gap.get('fixture_id', '')}]: "
            f"{gap.get('reason', '')}"
        )
    return rows


def _overall_verdict(
    scoreboard: dict[str, Any], fixture_count: int, pass_threshold: float
) -> str:
    if fixture_count == 0:
        return "NO_DATA"
    if scoreboard.get("has_error", False):
        return "FAIL"

    totals = scoreboard.get("totals", {})
    if _non_gap_pass_rate(totals) >= pass_threshold:
        return "PASS"
    return "FAIL"


def _gate_marker(counts: dict[str, int], pass_threshold: float) -> str:
    if _count(counts, "ERROR") > 0:
        return "FAIL"
    if _non_gap_pass_rate(counts) >= pass_threshold:
        return "PASS"
    return "FAIL"


def _non_gap_pass_rate(counts: dict[str, int]) -> float:
    non_gap_total = sum(_count(counts, status) for status in STATUSES if status != "GAP")
    if non_gap_total == 0:
        return 0.0
    return _count(counts, "PASS") / non_gap_total


def _format_percent(rate: float) -> str:
    return f"{rate * 100:.2f}%"


def _count(counts: dict[str, int], status: str) -> int:
    return int(counts.get(status, 0))
