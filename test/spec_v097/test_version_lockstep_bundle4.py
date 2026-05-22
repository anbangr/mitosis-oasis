# =========== Copyright 2023 @ CAMEL-AI.org. All Rights Reserved. ===========
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
# =========== Copyright 2023 @ CAMEL-AI.org. All Rights Reserved. ===========
r"""Feature 13 — v0.7.0 release-gate tests (Bundle 4 Execution State Machine).

T1  All four version surfaces lockstep at 0.7.0, no stale 0.6.0.
T2  CHANGELOG [0.7.0] block lists all Bundle-4 mechanisms.
T3  CHANGELOG [0.7.0] block cites the required spec sections.
T4  CHANGELOG [0.7.0] block names every new table / column / endpoint.
T5  Full pytest suite green with zero new skips/xfails.
T6  apscheduler shuts down cleanly under test (no Future-pending warnings).
T7  Lint and format are clean.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

import pytest
import tomlkit

from oasis.crypto.typed_data import DOMAIN


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


VERSION_SURFACES = [
    ("pyproject.toml", None),
    ("oasis/__init__.py", None),
    ("oasis/api.py", None),
    ("oasis/crypto/typed_data.py:DOMAIN", "version"),
]


def _read_file_text(rel_path: str) -> str:
    project_root = Path(__file__).parent.parent.parent
    full = project_root / rel_path.split(":")[0]
    return full.read_text()


def _read_pyproject_version() -> str:
    with open("pyproject.toml") as f:
        doc = tomlkit.parse(f.read())
    if "tool" in doc and "poetry" in doc["tool"]:
        return doc["tool"]["poetry"]["version"]
    if "project" in doc:
        return doc["project"]["version"]
    raise KeyError("No version key found under [tool.poetry] or [project]")


def _changelog_block(version: str) -> str:
    with open("CHANGELOG.md") as f:
        content = f.read()
    start = content.find(f"## [{version}]")
    assert start != -1, f"CHANGELOG.md missing ## [{version}] section"
    next_header = content.find("\n## [", start + 1)
    return content[start:next_header] if next_header != -1 else content[start:]


# ---------------------------------------------------------------------------
# T1 — Version lockstep at 0.7.0, no stale 0.6.0
# ---------------------------------------------------------------------------


def test_t1_pyproject_version_is_070():
    """tool.poetry.version must equal '0.7.0'."""
    version = _read_pyproject_version()
    assert version == "0.7.0", (
        f"pyproject.toml version is {version!r}, expected '0.7.0'"
    )


def test_t1_init_version_is_070():
    """oasis/__init__.py must declare __version__ = '0.7.0'."""
    text = _read_file_text("oasis/__init__.py")
    matches = re.findall(r'__version__\s*=\s*"0\.7\.0"', text)
    assert len(matches) >= 1, "oasis/__init__.py missing __version__ = '0.7.0'"


def test_t1_api_version_is_070():
    """oasis/api.py FastAPI app must pass version='0.7.0'."""
    text = _read_file_text("oasis/api.py")
    matches = re.findall(r'version\s*=\s*"0\.7\.0"', text)
    assert len(matches) >= 1, "oasis/api.py missing version='0.7.0' in FastAPI(...)"


def test_t1_domain_version_is_070():
    """DOMAIN['version'] must equal '0.7.0'."""
    assert DOMAIN["version"] == "0.7.0", (
        f"DOMAIN['version']={DOMAIN['version']!r}, expected '0.7.0'"
    )


def test_t1_no_stale_060_anywhere():
    """None of the four version surfaces may contain the string '0.6.0'."""
    files = [
        "pyproject.toml",
        "oasis/__init__.py",
        "oasis/api.py",
        "oasis/crypto/typed_data.py",
    ]
    offenders = []
    for rel in files:
        text = _read_file_text(rel)
        if '"0.6.0"' in text or "'0.6.0'" in text:
            offenders.append(rel)
    assert not offenders, f"Stale '0.6.0' still present in: {offenders}"


# ---------------------------------------------------------------------------
# T2 — CHANGELOG lists all Bundle 4 mechanisms
# ---------------------------------------------------------------------------


def test_t2_changelog_070_lists_all_mechanisms():
    r"""The [0.7.0] block must mention every Bundle-4 mechanism by name."""
    block = _changelog_block("0.7.0")
    required = [
        "9-state execution machine",
        "7-stage pipeline",
    ]
    missing = [s for s in required if s not in block]
    assert not missing, f"CHANGELOG [0.7.0] missing mechanisms: {missing}"


# ---------------------------------------------------------------------------
# T3 — CHANGELOG cites spec sections
# ---------------------------------------------------------------------------


def test_t3_changelog_070_cites_spec_sections():
    r"""The [0.7.0] block must cite the required spec paragraphs."""
    block = _changelog_block("0.7.0")
    required = [
        "spec exec §0.4",
    ]
    missing = [s for s in required if s not in block]
    assert not missing, f"CHANGELOG [0.7.0] missing spec citations: {missing}"


# ---------------------------------------------------------------------------
# T4 — CHANGELOG names all new tables + columns + endpoints
# ---------------------------------------------------------------------------


def test_t4_changelog_070_names_new_schema_items():
    r"""The [0.7.0] block must name every new table, column, and endpoint."""
    block = _changelog_block("0.7.0")
    required = [
        "task_assignment.state",
        "task_assignment.stage",
        "task_state_transition",
        "GET /api/execution/tasks/{task_id}/transitions",
    ]
    missing = [s for s in required if s not in block]
    assert not missing, f"CHANGELOG [0.7.0] missing schema items: {missing}"


# ---------------------------------------------------------------------------
# T5 — Full pytest suite green
# ---------------------------------------------------------------------------


def test_t5_full_pytest_suite_passes():
    """pytest -q test/ must exit 0 with no failures.

    Guard env-var prevents infinite recursion when this test spawns a
    subprocess that also tries to run itself.
    """
    if os.environ.get("PYTEST_IN_SUBPROCESS"):
        pytest.skip("Skipping recursive subprocess invocation")

    env = os.environ.copy()
    env["PYTEST_IN_SUBPROCESS"] = "1"

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            "test/",
            "--ignore=test/cross_branch/test_release_v030_gates.py",
            "--ignore=test/spec_v097/test_version_lockstep_bundle2.py",
            "--ignore=test/spec_v097/test_version_lockstep_bundle3.py",
            "--ignore=test/spec_v097/test_version_lockstep_bundle4.py",
        ],
        capture_output=True,
        text=True,
        env=env,
    )
    assert result.returncode == 0, (
        f"pytest -q test/ failed (exit {result.returncode}):\n"
        f"--- stdout ---\n{result.stdout}\n"
        f"--- stderr ---\n{result.stderr}"
    )


def test_t5_no_pytest_mark_skip_or_xfail():
    r"""No new ``pytest.mark.skip`` or ``pytest.mark.xfail`` in test/."""
    result = subprocess.run(
        [
            "grep",
            "-rE",
            "--include=*.py",
            r"@pytest\.mark\.(skip|xfail)\b",
            "test/",
        ],
        capture_output=True,
        text=True,
    )
    self_name = os.path.basename(__file__)
    lines = [
        line
        for line in result.stdout.splitlines()
        if self_name not in line and "__pycache__" not in line
    ]
    assert not lines, "Forbidden pytest.mark.skip/xfail found in test/:\n" + "\n".join(
        lines
    )


# ---------------------------------------------------------------------------
# T6 — apscheduler shuts down cleanly
# ---------------------------------------------------------------------------


def test_t6_apscheduler_no_pending_futures():
    """Watchdog + freeze-sweeper tests must emit no 'Future pending' warnings.

    Runs the adjudication and e2e suites with Deprecation- and
    Resource-Warnings escalated to errors.
    """
    if os.environ.get("PYTEST_IN_SUBPROCESS"):
        pytest.skip("Skipping recursive subprocess invocation")

    env = os.environ.copy()
    env["PYTEST_IN_SUBPROCESS"] = "1"

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "test/adjudication/",
            "test/e2e/",
            "-q",
            "-W",
            "error::DeprecationWarning",
            "-W",
            "error::ResourceWarning",
            "--ignore=test/cross_branch/test_release_v030_gates.py",
            "--ignore=test/spec_v097/test_version_lockstep_bundle2.py",
            "--ignore=test/spec_v097/test_version_lockstep_bundle3.py",
            "--ignore=test/spec_v097/test_version_lockstep_bundle4.py",
        ],
        capture_output=True,
        text=True,
        env=env,
    )
    combined = result.stdout + result.stderr
    assert "Future pending after test" not in combined, (
        "apscheduler leaked a pending Future:\n" + combined
    )
    assert "unclosed" not in combined.lower() or "event loop" not in combined.lower(), (
        "apscheduler or asyncio leaked an unclosed resource:\n" + combined
    )
    assert result.returncode == 0, (
        f"pytest test/adjudication/ test/e2e/ failed (exit {result.returncode}):\n"
        f"--- stdout ---\n{result.stdout}\n"
        f"--- stderr ---\n{result.stderr}"
    )


# ---------------------------------------------------------------------------
# T7 — Lint + format clean
# ---------------------------------------------------------------------------


def test_t7_ruff_check_clean():
    """python -m ruff check oasis/ test/ must exit 0."""
    result = subprocess.run(
        [sys.executable, "-m", "ruff", "check", "oasis/", "test/"],
        capture_output=True,
        text=True,
    )
    if result.returncode == 127 or "No module named" in result.stderr:
        pytest.skip("ruff not installed in this environment")
    assert result.returncode == 0, (
        f"ruff check failed:\n{result.stdout}\n{result.stderr}"
    )


def test_t7_ruff_format_produces_zero_diff():
    """python -m ruff format --diff oasis/ test/ must be empty."""
    result = subprocess.run(
        [sys.executable, "-m", "ruff", "format", "--diff", "oasis/", "test/"],
        capture_output=True,
        text=True,
    )
    if result.returncode == 127 or "No module named" in result.stderr:
        pytest.skip("ruff not installed in this environment")
    assert result.stdout.strip() == "", (
        f"ruff format would produce changes:\n{result.stdout}"
    )
