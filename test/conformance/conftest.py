"""Pytest wiring for Phase-1 conformance replay tests."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from oasis.observatory.event_bus import EventBus


REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURE_ROOT = REPO_ROOT / "test" / "conformance" / "fixtures" / "legislation"


@pytest.fixture(autouse=True)
def _seed_event_bus(tmp_path: Path):
    """Give every conformance test a clean, initialised EventBus."""
    EventBus.reset()
    EventBus.get_instance(db_path=tmp_path / "obs.db")
    try:
        yield
    finally:
        EventBus.reset()


def _sha_file_candidates() -> list[Path]:
    return [
        REPO_ROOT / "agent-city-contract" / ".contracts-sha",
        REPO_ROOT.parent / "agent-city-contract" / ".contracts-sha",
        REPO_ROOT / ".contracts-sha",
    ]


def _contract_core_candidates() -> list[Path]:
    return [
        REPO_ROOT / "agent-city-contract" / "contracts" / "src" / "core",
        REPO_ROOT.parent / "agent-city-contract" / "contracts" / "src" / "core",
    ]


def compute_external_contracts_sha() -> str:
    """Return the AgentCity core-contract SHA from a lockfile or source bytes."""
    for core_dir in _contract_core_candidates():
        if not core_dir.exists():
            continue
        sol_files = sorted(core_dir.glob("*.sol"))
        if not sol_files:
            continue
        digest = hashlib.sha256()
        for path in sol_files:
            digest.update(path.read_bytes())
        return "0x" + digest.hexdigest()

    for sha_file in _sha_file_candidates():
        if sha_file.exists():
            value = sha_file.read_text().strip()
            if value:
                return value

    pytest.fail(
        "external contract SHA unavailable: expected .contracts-sha or "
        "agent-city-contract/contracts/src/core/*.sol"
    )


@pytest.fixture
def external_contracts_sha() -> str:
    return compute_external_contracts_sha()


def validate_contracts_sha(
    fixture_root: Path = FIXTURE_ROOT, external_contracts_sha: str | None = None
) -> str:
    """Validate that the fixture corpus is coherent and matches live contracts."""
    root = Path(fixture_root)
    fixture_paths = sorted(root.rglob("*.json"))
    if not fixture_paths:
        pytest.fail("no fixtures, refusing to publish a report")

    observed: set[str] = set()
    for path in fixture_paths:
        payload = json.loads(path.read_text())
        source = payload.get("source") or {}
        contracts_sha = source.get("contracts_sha")
        if not contracts_sha:
            pytest.fail(f"fixture {path} missing source.contracts_sha")
        observed.add(contracts_sha)

    if len(observed) > 1:
        pytest.fail(f"mixed contracts_sha across fixture corpus: {sorted(observed)}")

    validated_sha = next(iter(observed))
    external_sha = external_contracts_sha or compute_external_contracts_sha()
    if validated_sha != external_sha:
        pytest.fail(
            f"fixture SHA {validated_sha} != external contract SHA {external_sha}; "
            "recapture fixtures or sync the contracts checkout"
        )

    return validated_sha


@pytest.fixture
def validated_contracts_sha(external_contracts_sha: str) -> str:
    return validate_contracts_sha(FIXTURE_ROOT, external_contracts_sha)
