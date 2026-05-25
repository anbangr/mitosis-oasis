"""Validate that every committed fixture file parses cleanly and is consistent
with the power_map.json registry.

These tests act as a sentinel: a corrupted, empty, or schema-mismatched fixture
will be caught here even though the 28 unit tests in other files never load the
on-disk corpus.
"""

from __future__ import annotations

import json
import re
import sys
import warnings
from pathlib import Path

import pytest
from pydantic import ValidationError

from test.conformance.oracle.schema import Fixture

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

_CONFORMANCE_DIR = Path(__file__).parent.parent
_FIXTURES_ROOT = _CONFORMANCE_DIR / "fixtures"
_POWER_MAP_PATH = _CONFORMANCE_DIR / "power_map.json"

# Collect fixture paths once at module load so parametrize IDs are stable.
_FIXTURE_PATHS: list[Path] = sorted(_FIXTURES_ROOT.rglob("*.json"))

# Raw hex address pattern (checksummed or lower)
_HEX_ADDRESS_RE = re.compile(r"^0x[0-9a-fA-F]{40}$")


def _load_power_map() -> dict:
    with _POWER_MAP_PATH.open() as fh:
        return json.load(fh)


def _fixture_id(path: Path) -> str:
    """Short human-readable ID for pytest output: last two path segments."""
    return "/".join(path.parts[-2:])


# ---------------------------------------------------------------------------
# Test: every fixture parses as Fixture (parameterized)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("fixture_path", _FIXTURE_PATHS, ids=_fixture_id)
def test_every_fixture_parses_as_Fixture(fixture_path: Path):
    """Each .json file under fixtures/ must deserialise without ValidationError."""
    raw = fixture_path.read_text()
    data = json.loads(raw)
    try:
        Fixture.model_validate(data)
    except ValidationError as exc:
        pytest.fail(
            f"Fixture {fixture_path.name} failed schema validation:\n{exc}"
        )


# ---------------------------------------------------------------------------
# Test: every fixture has at least one call (soft warning, not hard fail)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("fixture_path", _FIXTURE_PATHS, ids=_fixture_id)
def test_every_fixture_has_at_least_one_call(fixture_path: Path):
    """Fixtures with an empty calls array are suspicious; emit a warning."""
    data = json.loads(fixture_path.read_text())
    fixture = Fixture.model_validate(data)
    if not fixture.calls:
        warnings.warn(
            f"Fixture {fixture_path.name} has an empty 'calls' array — "
            "it exercises no contract behaviour.",
            stacklevel=2,
        )
        # Not a hard failure: the fixture may be intentionally minimal.
        # The warning surfaces in pytest output so a human can investigate.


# ---------------------------------------------------------------------------
# Test: primary_contract must be a key in power_map.by_contract
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("fixture_path", _FIXTURE_PATHS, ids=_fixture_id)
def test_every_fixture_primary_contract_is_in_power_map(fixture_path: Path):
    """fixture.primary_contract must appear as a key in power_map.json."""
    power_map = _load_power_map()
    by_contract: dict = power_map.get("by_contract", {})

    data = json.loads(fixture_path.read_text())
    fixture = Fixture.model_validate(data)

    assert fixture.primary_contract in by_contract, (
        f"Fixture {fixture_path.name}: primary_contract "
        f"'{fixture.primary_contract}' is not in power_map.json. "
        f"Known contracts: {sorted(by_contract)}"
    )


# ---------------------------------------------------------------------------
# Test: every call's target_contract is known or is a raw hex address
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("fixture_path", _FIXTURE_PATHS, ids=_fixture_id)
def test_every_call_target_contract_is_known_or_hex(fixture_path: Path):
    """Each call.target_contract must be in power_map OR a 0x-prefixed address."""
    power_map = _load_power_map()
    by_contract: dict = power_map.get("by_contract", {})

    data = json.loads(fixture_path.read_text())
    fixture = Fixture.model_validate(data)

    for call in fixture.calls:
        tc = call.target_contract
        is_known = tc in by_contract
        is_hex = bool(_HEX_ADDRESS_RE.match(tc))
        assert is_known or is_hex, (
            f"Fixture {fixture_path.name} call[{call.idx}]: "
            f"target_contract '{tc}' is neither in power_map.json nor a "
            "raw hex address (^0x[0-9a-fA-F]{{40}}$)."
        )


# ---------------------------------------------------------------------------
# Test: power_map.json structural integrity
# ---------------------------------------------------------------------------

def test_power_map_schema_version_is_1():
    """power_map.json must declare schema_version==1 and a non-empty by_contract."""
    power_map = _load_power_map()
    assert power_map.get("schema_version") == 1, (
        f"Expected schema_version 1, got {power_map.get('schema_version')!r}"
    )
    by_contract = power_map.get("by_contract")
    assert isinstance(by_contract, dict) and by_contract, (
        "power_map.json must contain a non-empty 'by_contract' dict"
    )
