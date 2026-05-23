# Licensed to the Apache Software Foundation (ASF) under one
# or more contributor license agreements.  See the NOTICE file
# distributed with this work for additional information
# regarding copyright ownership.  The ASF licenses this file
# to you under the Apache License, Version 2.0 (the
# "License"); you may not use this file except in compliance
# with the License.  You may obtain a copy of the License at
#
#   http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing,
# software distributed under the License is distributed on an
# "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY
# KIND, either express or implied.  See the License for the
# specific language governing permissions and limitations
# under the License.
r"""Bundle 5 — v0.8.0 release-gate tests (Legislative Dynamics).

T1  All four version surfaces lockstep at 0.8.0, no stale 0.7.0.
T2  CHANGELOG [0.8.0] block lists all Bundle-5 mechanisms.
T3  CHANGELOG [0.8.0] block cites the required spec sections.
T4  CHANGELOG [0.8.0] block names every new table / column / endpoint.
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


_BUNDLE_IGNORES = [
    "--ignore=test/cross_branch/test_release_v030_gates.py",
    "--ignore=test/spec_v097/test_version_lockstep_bundle5.py",
]


# ---------------------------------------------------------------------------
# T1 — Version lockstep at 0.8.0
# ---------------------------------------------------------------------------


def test_t1_pyproject_version_is_080() -> None:
    version = _read_pyproject_version()
    assert version == "0.8.0", (
        f"pyproject.toml version is {version!r}, expected '0.8.0'"
    )


def test_t1_init_version_is_080() -> None:
    text = _read_file_text("oasis/__init__.py")
    assert re.search(r'__version__\s*=\s*"0\.8\.0"', text), (
        "oasis/__init__.py missing __version__ = '0.8.0'"
    )


def test_t1_api_version_is_080() -> None:
    text = _read_file_text("oasis/api.py")
    assert re.search(r'version\s*=\s*"0\.8\.0"', text), (
        "oasis/api.py missing version='0.8.0' in FastAPI(...)"
    )


def test_t1_domain_version_is_080() -> None:
    assert DOMAIN["version"] == "0.8.0", (
        f"DOMAIN['version']={DOMAIN['version']!r}, expected '0.8.0'"
    )


def test_t1_no_stale_070_in_runtime_surfaces() -> None:
    """The four runtime surfaces must not contain '0.7.0'."""
    files = [
        "pyproject.toml",
        "oasis/__init__.py",
        "oasis/api.py",
        "oasis/crypto/typed_data.py",
    ]
    offenders = [rel for rel in files if '"0.7.0"' in _read_file_text(rel)]
    assert not offenders, f"Stale '0.7.0' still present in: {offenders}"


# ---------------------------------------------------------------------------
# T2 — CHANGELOG mechanisms
# ---------------------------------------------------------------------------


def test_t2_changelog_080_lists_all_mechanisms() -> None:
    block = _changelog_block("0.8.0")
    required = [
        "Adaptive refinement",
        "Milestone trigger",
        "Petition trigger",
        "Sponsorship threshold",
        "Frozen evidence rule",
    ]
    missing = [s for s in required if s not in block]
    assert not missing, f"CHANGELOG [0.8.0] missing mechanisms: {missing}"


# ---------------------------------------------------------------------------
# T3 — CHANGELOG cites spec sections
# ---------------------------------------------------------------------------


def test_t3_changelog_080_cites_spec_sections() -> None:
    block = _changelog_block("0.8.0")
    required = [
        "spec leg §1.10",
        "spec §2.2",
        "spec §4",
        "spec §5",
    ]
    missing = [s for s in required if s not in block]
    assert not missing, f"CHANGELOG [0.8.0] missing spec citations: {missing}"


# ---------------------------------------------------------------------------
# T4 — CHANGELOG names new tables / columns / params
# ---------------------------------------------------------------------------


def test_t4_changelog_080_names_new_schema_items() -> None:
    block = _changelog_block("0.8.0")
    required = [
        "petition",
        "petition_signature",
        "evidence_anchor",
        "parent_task_id",
        "iteration",
        "sponsorship_min",
        "milestone_round_interval",
        "petition_threshold",
        "adaptive_iteration_budget",
    ]
    missing = [s for s in required if s not in block]
    assert not missing, f"CHANGELOG [0.8.0] missing schema items: {missing}"


# ---------------------------------------------------------------------------
# T5 — Full suite green
# ---------------------------------------------------------------------------


def test_t5_full_pytest_suite_passes() -> None:
    if os.environ.get("PYTEST_IN_SUBPROCESS"):
        pytest.skip("Skipping recursive subprocess invocation")

    env = os.environ.copy()
    env["PYTEST_IN_SUBPROCESS"] = "1"

    result = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "test/", *_BUNDLE_IGNORES],
        capture_output=True,
        text=True,
        env=env,
    )
    assert result.returncode == 0, (
        f"pytest -q test/ failed (exit {result.returncode}):\n"
        f"--- stdout ---\n{result.stdout}\n"
        f"--- stderr ---\n{result.stderr}"
    )


def test_t5_no_pytest_mark_skip_or_xfail() -> None:
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
    assert not lines, "Forbidden pytest.mark.skip/xfail in test/:\n" + "\n".join(lines)


# ---------------------------------------------------------------------------
# T6 — apscheduler clean shutdown
# ---------------------------------------------------------------------------


def test_t6_apscheduler_no_pending_futures() -> None:
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
            *_BUNDLE_IGNORES,
        ],
        capture_output=True,
        text=True,
        env=env,
    )
    combined = result.stdout + result.stderr
    assert "Future pending after test" not in combined, (
        "apscheduler leaked a pending Future:\n" + combined
    )
    assert result.returncode == 0, (
        f"pytest test/adjudication/ test/e2e/ failed (exit {result.returncode}):\n"
        f"--- stdout ---\n{result.stdout}\n"
        f"--- stderr ---\n{result.stderr}"
    )


# ---------------------------------------------------------------------------
# T7 — Lint + format
# ---------------------------------------------------------------------------


def test_t7_ruff_check_clean() -> None:
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


def test_t7_ruff_format_produces_zero_diff() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "ruff", "format", "--diff", "oasis/", "test/"],
        capture_output=True,
        text=True,
    )
    if result.returncode == 127 or "No module named" in result.stderr:
        pytest.skip("ruff not installed in this environment")
    assert result.returncode == 0 and result.stdout.strip() == "", (
        f"ruff format produced a diff:\n{result.stdout}"
    )
