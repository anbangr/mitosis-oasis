"""End-to-end replay driver for Phase-1 conformance fixtures."""

from __future__ import annotations

import json
import subprocess
from datetime import datetime, timezone

UTC = timezone.utc
from pathlib import Path

import pytest

import test.conformance.adapter.constitutional_review  # noqa: F401
import test.conformance.adapter.legislative_pipeline  # noqa: F401
import test.conformance.adapter.codification_module  # noqa: F401
import test.conformance.adapter.voting_verifier  # noqa: F401
import test.conformance.adapter.governance_registry  # noqa: F401
from test.conformance.adapter import registry
from test.conformance.adapter.event_capture import EventCollector
from test.conformance.matrix import report, scoreboard
from test.conformance.oracle.diff import DiffOptions, diff_call
from test.conformance.oracle.schema import CallVerdict, Fixture, FixtureCall


pytestmark = pytest.mark.conformance

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_FIXTURE_ROOT = REPO_ROOT / "test" / "conformance" / "fixtures" / "legislation"
DEFAULT_REPORT_ROOT = REPO_ROOT / "test" / "conformance" / "reports"

PHASE1_POWER_MAP = {
    "ConstitutionalReview": "legislation",
    "LegislativePipeline": "legislation",
    "CodificationModule": "legislation",
    "VotingVerifier": "legislation",
    "GovernanceRegistry": "legislation",
}


def git_head_short_sha() -> str:
    return subprocess.check_output(
        ["git", "rev-parse", "--short", "HEAD"],
        cwd=REPO_ROOT,
        text=True,
    ).strip()


def _default_run_id() -> str:
    return f"{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}-{git_head_short_sha()}"


def _fixture_id(fixture_root: Path, path: Path) -> str:
    try:
        return str(path.with_suffix("").relative_to(fixture_root.parent))
    except ValueError:
        return str(path.with_suffix(""))


def _load_fixture(path: Path) -> Fixture:
    text = path.read_text()
    if hasattr(Fixture, "model_validate_json"):
        return Fixture.model_validate_json(text)
    return Fixture.parse_raw(text)


def _gap_verdict(call: FixtureCall, fixture_id: str, power: str) -> CallVerdict:
    return CallVerdict(
        verdict="GAP",
        fixture_id=fixture_id,
        call_idx=call.idx,
        contract=call.target_contract,
        function=call.function,
        power=power,
        diff={"reason": "adapter_not_registered"},
    )


def _error_verdict(
    call: FixtureCall, fixture_id: str, power: str, exc: BaseException
) -> CallVerdict:
    return CallVerdict(
        verdict="ERROR",
        fixture_id=fixture_id,
        call_idx=call.idx,
        contract=call.target_contract,
        function=call.function,
        power=power,
        error=f"{type(exc).__name__}: {exc}",
    )


def _dispatch_call(call: FixtureCall, fixture_id: str, power: str) -> CallVerdict:
    adapter_fn = registry.lookup(call.target_contract, call.function)
    if adapter_fn is None:
        return _gap_verdict(call, fixture_id, power)

    try:
        with EventCollector():
            actual = adapter_fn(call)
    except RuntimeError as exc:
        if "EventCollector requires an initialised EventBus" in str(exc):
            pytest.fail(f"ERROR on bus-not-seeded: {exc}")
        return _error_verdict(call, fixture_id, power, exc)
    except Exception as exc:
        return _error_verdict(call, fixture_id, power, exc)

    if isinstance(actual, CallVerdict):
        return actual
    return diff_call(
        expected=call,
        actual=actual,
        opts=DiffOptions(),
        fixture_id=fixture_id,
        power=power,
    )


def run_replay(
    fixture_root: Path = DEFAULT_FIXTURE_ROOT,
    reports_root: Path = DEFAULT_REPORT_ROOT,
    validated_contracts_sha: str | None = None,
    run_id: str | None = None,
):
    if validated_contracts_sha is None:
        pytest.fail("validated_contracts_sha is required; run the SHA gate first")

    root = Path(fixture_root)
    fixture_paths = sorted(root.rglob("*.json"))
    if not fixture_paths:
        pytest.fail("no fixtures, refusing to publish a report")

    loaded_fixtures: list[Fixture] = []
    verdicts: list[CallVerdict] = []
    for path in fixture_paths:
        fixture = _load_fixture(path)
        loaded_fixtures.append(fixture)
        fixture_id = _fixture_id(root, path)
        for call in fixture.calls:
            verdicts.append(_dispatch_call(call, fixture_id, fixture.power))

    fixture_count = len(loaded_fixtures)
    call_count = sum(len(fixture.calls) for fixture in loaded_fixtures)
    replay_scoreboard = scoreboard.aggregate(
        verdicts,
        power_map=PHASE1_POWER_MAP,
        top_n=10,
    )
    report.write_report(
        replay_scoreboard,
        contracts_sha=validated_contracts_sha,
        run_id=run_id or _default_run_id(),
        fixture_count=fixture_count,
        call_count=call_count,
        out_root=Path(reports_root),
    )

    if replay_scoreboard.has_error:
        pytest.fail("ERROR=0 harness-correctness gate failed")
    return replay_scoreboard


def test_replay(validated_contracts_sha: str):
    run_replay(
        fixture_root=DEFAULT_FIXTURE_ROOT,
        reports_root=DEFAULT_REPORT_ROOT,
        validated_contracts_sha=validated_contracts_sha,
    )
