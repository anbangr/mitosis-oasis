"""Report writer for conformance replay scoreboards."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from test.conformance.matrix.scoreboard import Scoreboard, VERDICTS


def _scoreboard_dict(scoreboard: Scoreboard | dict) -> dict:
    if hasattr(scoreboard, "to_dict"):
        return scoreboard.to_dict()
    return scoreboard


def _gate(counts: dict[str, int]) -> str:
    return "PASS" if counts.get("FAIL", 0) == 0 and counts.get("GAP", 0) == 0 else "FAIL"


def _render_top(title: str, rows: list[dict]) -> list[str]:
    lines = [f"## {title}", ""]
    if not rows:
        lines.extend(["None.", ""])
        return lines
    for item in rows:
        lines.append(
            "- "
            + f"{item.get('fixture_id')} call {item.get('call_idx')} "
            + f"{item.get('contract')}.{item.get('function')}"
        )
    lines.append("")
    return lines


def _render_markdown(payload: dict) -> str:
    metadata = payload["metadata"]
    scoreboard = payload["scoreboard"]
    lines = [
        "# Conformance Report",
        "",
        f"- contracts_sha: `{metadata['contracts_sha']}`",
        f"- run_id: `{metadata['run_id']}`",
        f"- fixture_count: {metadata['fixture_count']}",
        f"- call_count: {metadata['call_count']}",
        "",
        "## Totals",
        "",
        "| PASS | FAIL | GAP | ERROR | Has error |",
        "| ---: | ---: | ---: | ---: | :--- |",
        "| "
        + " | ".join(str(scoreboard["totals"].get(v, 0)) for v in VERDICTS)
        + f" | {scoreboard['has_error']} |",
        "",
        "## Per-power Gate",
        "",
        "| Power | PASS | FAIL | GAP | ERROR | Gate |",
        "| :--- | ---: | ---: | ---: | ---: | :--- |",
    ]
    for power, counts in sorted(scoreboard["by_power"].items()):
        lines.append(
            "| "
            + power
            + " | "
            + " | ".join(str(counts.get(v, 0)) for v in VERDICTS)
            + f" | {_gate(counts)} |"
        )
    lines.append("")
    lines.extend(_render_top("Top FAILures", scoreboard["top_failures"]))
    lines.extend(_render_top("Top GAPs", scoreboard["top_gaps"]))
    return "\n".join(lines)


def write_report(
    scoreboard: Scoreboard | dict,
    contracts_sha: str,
    run_id: str,
    fixture_count: int,
    call_count: int,
    out_root: Path,
) -> Path:
    out_dir = Path(out_root) / contracts_sha
    out_dir.mkdir(parents=True, exist_ok=True)

    payload = {
        "metadata": {
            "contracts_sha": contracts_sha,
            "run_id": run_id,
            "generated_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "fixture_count": fixture_count,
            "call_count": call_count,
        },
        "scoreboard": _scoreboard_dict(scoreboard),
    }

    (out_dir / "conformance.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n"
    )
    (out_dir / "conformance.md").write_text(_render_markdown(payload) + "\n")
    return out_dir
