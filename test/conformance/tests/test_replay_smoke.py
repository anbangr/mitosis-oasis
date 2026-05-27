"""Contract tests for the Phase 8.1 replay driver and SHA gate.

These tests intentionally assume the replay driver/conftest helpers exist.
The primary implementation phase supplies them after this RED phase.
"""

from __future__ import annotations

import hashlib
import importlib
import json
import re
from pathlib import Path

import pytest

from oasis.observatory.event_bus import EventBus
from oasis.observatory.events import Event, EventType
from test.conformance.oracle.schema import CallResult


pytestmark = pytest.mark.conformance

_VALIDATED_SHA = (
    "0xaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
)
_EXTERNAL_SHA = "0xbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"


def _replay_module():
    try:
        return importlib.import_module("test.conformance.test_replay")
    except ModuleNotFoundError as exc:
        pytest.fail(
            f"expected Phase 8.1 replay driver module to exist: {exc}",
            pytrace=False,
        )


def _conftest_module():
    try:
        return importlib.import_module("test.conformance.conftest")
    except ModuleNotFoundError as exc:
        pytest.fail(
            f"expected Phase 8.1 conftest module to exist: {exc}",
            pytrace=False,
        )


def _validate_contracts_sha(fixture_root: Path, external_sha: str) -> str:
    conftest = _conftest_module()
    gate = getattr(conftest, "validate_contracts_sha", None)
    assert callable(gate), "conftest must expose validate_contracts_sha helper"
    return gate(fixture_root=fixture_root, external_contracts_sha=external_sha)


def _run_replay(
    fixture_root: Path,
    reports_root: Path,
    validated_sha: str,
    run_id: str = "20260527T000000Z-deadbee",
):
    replay = _replay_module()
    run_replay = getattr(replay, "run_replay", None)
    assert callable(run_replay), "test_replay must expose run_replay helper"
    return run_replay(
        fixture_root=fixture_root,
        reports_root=reports_root,
        validated_contracts_sha=validated_sha,
        run_id=run_id,
    )


def _fixture_payload(sha: str | None, calls: list[dict] | None = None) -> dict:
    source = {
        "foundry_test": "test/ReplaySmoke.t.sol:ReplaySmokeTest::test_smoke()",
        "captured_at": "2026-05-27T00:00:00Z",
        "solc_version": "0.8.28",
        "forge_json_version": "1.5.1-stable",
    }
    if sha is not None:
        source["contracts_sha"] = sha

    return {
        "fixture_version": 1,
        "source": source,
        "power": "legislation",
        "primary_contract": "ConstitutionalReview",
        "test_status": "Success",
        "calls": calls
        if calls is not None
        else [
            {
                "idx": 0,
                "target_contract": "ConstitutionalReview",
                "selector": "0x11111111",
                "function": "smokeFirst()",
                "args": [],
                "msg_sender": "0x0000000000000000000000000000000000000001",
                "value_wei": "0",
                "result": {"kind": "ok", "return_data": "0x"},
                "events": [],
                "state_delta": [],
                "revert_reason": None,
            },
            {
                "idx": 1,
                "target_contract": "ConstitutionalReview",
                "selector": "0x22222222",
                "function": "smokeSecond()",
                "args": [],
                "msg_sender": "0x0000000000000000000000000000000000000001",
                "value_wei": "0",
                "result": {"kind": "ok", "return_data": "0x"},
                "events": [],
                "state_delta": [],
                "revert_reason": None,
            },
        ],
    }


def _write_fixture(
    fixture_root: Path,
    contract: str,
    name: str,
    sha: str | None,
    calls: list[dict] | None = None,
) -> Path:
    path = fixture_root / contract / f"{name}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(_fixture_payload(sha, calls), indent=2))
    return path


def _read_report(reports_root: Path, sha: str) -> dict:
    report_path = reports_root / sha / "conformance.json"
    assert report_path.exists(), f"missing report JSON at {report_path}"
    return json.loads(report_path.read_text())


def _assert_legislative_rollup_matches_totals(report_json: dict) -> None:
    totals = report_json["scoreboard"]["totals"]
    legislative = report_json["scoreboard"]["by_power"]["legislative"]
    assert legislative == totals


def test_replay_smoke_runs_stub_corpus_and_writes_validated_sha_report(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    fixture_root = tmp_path / "fixtures" / "legislation"
    reports_root = tmp_path / "reports"
    _write_fixture(fixture_root, "ConstitutionalReview", "smoke", _VALIDATED_SHA)

    from test.conformance.adapter import registry

    monkeypatch.setitem(
        registry.CONTRACT_FN_MAP,
        ("ConstitutionalReview", "smokeFirst()"),
        lambda call: CallResult(ok=True, events=[], state_delta=[], return_data=[]),
    )
    monkeypatch.setitem(
        registry.CONTRACT_FN_MAP,
        ("ConstitutionalReview", "smokeSecond()"),
        lambda call: CallResult(ok=True, events=[], state_delta=[], return_data=[]),
    )

    validated_sha = _validate_contracts_sha(fixture_root, _VALIDATED_SHA)
    scoreboard = _run_replay(fixture_root, reports_root, validated_sha)

    assert getattr(scoreboard, "has_error") is False
    report_json = _read_report(reports_root, _VALIDATED_SHA)
    assert report_json["metadata"]["contracts_sha"] == _VALIDATED_SHA
    assert report_json["metadata"]["fixture_count"] == 1
    assert report_json["metadata"]["call_count"] == 2
    assert report_json["metadata"]["run_id"]
    assert report_json["scoreboard"]["has_error"] is False
    _assert_legislative_rollup_matches_totals(report_json)


def test_full_corpus_replay_writes_one_validated_report_with_phase1_gate(
    tmp_path: Path,
):
    fixture_root = Path("test/conformance/fixtures/legislation")
    fixture_paths = sorted(fixture_root.rglob("*.json"))
    assert fixture_paths, "full corpus must contain Phase-1 fixtures"
    fixture_shas = {
        json.loads(path.read_text())["source"]["contracts_sha"]
        for path in fixture_paths
    }
    assert len(fixture_shas) == 1, "full corpus must already be SHA coherent"
    validated_sha = next(iter(fixture_shas))
    expected_call_count = sum(
        len(json.loads(path.read_text())["calls"]) for path in fixture_paths
    )

    scoreboard = _run_replay(fixture_root, tmp_path / "reports", validated_sha)

    report_json = _read_report(tmp_path / "reports", validated_sha)
    assert getattr(scoreboard, "has_error") is False
    assert report_json["metadata"]["contracts_sha"] == validated_sha
    assert report_json["metadata"]["fixture_count"] == len(fixture_paths)
    assert report_json["metadata"]["call_count"] == expected_call_count
    assert report_json["metadata"]["fixture_count"] > 0
    assert report_json["metadata"]["call_count"] > 0
    assert report_json["scoreboard"]["has_error"] is False
    _assert_legislative_rollup_matches_totals(report_json)

    totals = report_json["scoreboard"]["totals"]
    expected_gate = "PASS" if totals.get("FAIL", 0) == 0 and totals.get("GAP", 0) == 0 else "FAIL"
    report_md = (tmp_path / "reports" / validated_sha / "conformance.md").read_text()
    legislative_lines = [
        line for line in report_md.splitlines() if "legislative" in line
    ]
    assert any(expected_gate in line for line in legislative_lines)


def test_adapter_modules_register_all_phase1_contracts_on_import():
    replay = _replay_module()
    assert replay.PHASE1_POWER_MAP == {
        "ConstitutionalReview": "legislative",
        "ConstitutionalParameters": "legislative",
        "LegislativePipeline": "legislative",
        "CodificationModule": "legislative",
        "VotingVerifier": "legislative",
        "GovernanceRegistry": "legislative",
    }

    expected_contracts = set(replay.PHASE1_POWER_MAP)
    for module_name in [
        "test.conformance.adapter.constitutional_review",
        "test.conformance.adapter.legislative_pipeline",
        "test.conformance.adapter.codification_module",
        "test.conformance.adapter.voting_verifier",
        "test.conformance.adapter.governance_registry",
    ]:
        importlib.import_module(module_name)

    from test.conformance.adapter.registry import CONTRACT_FN_MAP

    registered_contracts = {contract for contract, _ in CONTRACT_FN_MAP}
    assert expected_contracts <= registered_contracts


def test_conformance_autouse_fixture_resets_and_seeds_event_bus():
    bus = EventBus.get_instance()
    assert bus.replay(limit=10) == []
    published = bus.publish(Event(event_type=EventType.SESSION_CREATED))
    assert published.sequence_number == 1


def test_conformance_autouse_fixture_starts_next_test_with_clean_bus():
    bus = EventBus.get_instance()
    assert bus.replay(limit=10) == []
    published = bus.publish(Event(event_type=EventType.SESSION_CREATED))
    assert published.sequence_number == 1


def test_mixed_sha_corpus_aborts_before_report_is_written(tmp_path: Path):
    fixture_root = tmp_path / "fixtures" / "legislation"
    reports_root = tmp_path / "reports"
    _write_fixture(fixture_root, "ConstitutionalReview", "first", _VALIDATED_SHA)
    _write_fixture(fixture_root, "LegislativePipeline", "second", _EXTERNAL_SHA)

    with pytest.raises(pytest.fail.Exception, match="mixed contracts_sha"):
        _validate_contracts_sha(fixture_root, _VALIDATED_SHA)

    assert not reports_root.exists()


def test_external_sha_mismatch_aborts_with_both_shas_and_no_report(tmp_path: Path):
    fixture_root = tmp_path / "fixtures" / "legislation"
    reports_root = tmp_path / "reports"
    _write_fixture(fixture_root, "ConstitutionalReview", "stale", _VALIDATED_SHA)

    with pytest.raises(
        pytest.fail.Exception,
        match=(
            re.escape(_VALIDATED_SHA)
            + r".*"
            + re.escape(_EXTERNAL_SHA)
            + r".*recapture fixtures or sync the contracts checkout"
        ),
    ):
        _validate_contracts_sha(fixture_root, _EXTERNAL_SHA)

    assert not reports_root.exists()


def test_missing_fixture_source_contracts_sha_names_offending_path(
    tmp_path: Path,
):
    fixture_root = tmp_path / "fixtures" / "legislation"
    missing_sha_path = _write_fixture(
        fixture_root, "ConstitutionalReview", "missing_sha", None
    )

    with pytest.raises(pytest.fail.Exception, match="missing source.contracts_sha") as exc:
        _validate_contracts_sha(fixture_root, _VALIDATED_SHA)

    assert str(missing_sha_path) in str(exc.value)
    assert not (tmp_path / "reports" / "unknown").exists()


def test_empty_fixture_corpus_aborts_instead_of_publishing_external_sha(
    tmp_path: Path,
):
    fixture_root = tmp_path / "fixtures" / "legislation" / "GovernanceRegistry"
    fixture_root.mkdir(parents=True)
    reports_root = tmp_path / "reports"

    with pytest.raises(
        pytest.fail.Exception,
        match="no fixtures, refusing to publish a report",
    ):
        _validate_contracts_sha(fixture_root.parent, _VALIDATED_SHA)

    assert not (reports_root / _VALIDATED_SHA).exists()


def test_external_contracts_sha_prefers_live_source_bytes_over_lockfile(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    conftest = _conftest_module()
    core_dir = tmp_path / "agent-city-contract" / "contracts" / "src" / "core"
    core_dir.mkdir(parents=True)
    first = core_dir / "A.sol"
    second = core_dir / "B.sol"
    first.write_text("contract A {}\n")
    second.write_text("contract B {}\n")
    stale_lockfile = tmp_path / ".contracts-sha"
    stale_lockfile.write_text(_VALIDATED_SHA)

    monkeypatch.setattr(conftest, "_contract_core_candidates", lambda: [core_dir])
    monkeypatch.setattr(conftest, "_sha_file_candidates", lambda: [stale_lockfile])

    digest = hashlib.sha256()
    for path in sorted([first, second]):
        digest.update(path.read_bytes())

    assert conftest.compute_external_contracts_sha() == "0x" + digest.hexdigest()


def test_adapter_exception_is_recorded_as_error_then_fails_error_zero_gate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    fixture_root = tmp_path / "fixtures" / "legislation"
    reports_root = tmp_path / "reports"
    _write_fixture(fixture_root, "ConstitutionalReview", "adapter_error", _VALIDATED_SHA)

    from test.conformance.adapter import registry

    def _explode(_call):
        raise RuntimeError("adapter blew up")

    monkeypatch.setitem(
        registry.CONTRACT_FN_MAP,
        ("ConstitutionalReview", "smokeFirst()"),
        _explode,
    )
    monkeypatch.setitem(
        registry.CONTRACT_FN_MAP,
        ("ConstitutionalReview", "smokeSecond()"),
        lambda call: CallResult(ok=True, events=[], state_delta=[], return_data=[]),
    )

    with pytest.raises(pytest.fail.Exception, match="ERROR=0"):
        _run_replay(fixture_root, reports_root, _VALIDATED_SHA)

    report_json = _read_report(reports_root, _VALIDATED_SHA)
    assert report_json["scoreboard"]["has_error"] is True
    assert report_json["scoreboard"]["totals"]["ERROR"] == 1


def test_git_head_short_sha_and_default_run_id_are_non_empty(tmp_path: Path):
    fixture_root = tmp_path / "fixtures" / "legislation"
    reports_root = tmp_path / "reports"
    _write_fixture(fixture_root, "ConstitutionalReview", "smoke", _VALIDATED_SHA)

    replay = _replay_module()
    short_sha = replay.git_head_short_sha()
    assert re.fullmatch(r"[0-9a-f]{7,12}", short_sha)

    _run_replay(fixture_root, reports_root, _VALIDATED_SHA, run_id=None)
    report_json = _read_report(reports_root, _VALIDATED_SHA)
    assert re.match(
        r"^\d{8}T\d{6}Z-[0-9a-f]{7,12}$",
        report_json["metadata"]["run_id"],
    )
