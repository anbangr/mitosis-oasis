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
"""Release-gate tests: version lockstep, CHANGELOG completeness, tooling hygiene.

These tests enforce the Bundle-1 release criteria (pyproject==0.4.0,
DOMAIN lockstep, CHANGELOG coverage, ruff cleanliness, no skips).
"""

from __future__ import annotations

import os
import subprocess
import sys

import pytest
import tomlkit

from oasis.crypto.typed_data import DOMAIN


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _read_pyproject_version() -> str:
    r"""Read version from ``pyproject.toml``, supporting Poetry and PEP-621 schemas."""
    with open("pyproject.toml") as f:
        doc = tomlkit.parse(f.read())

    if "tool" in doc and "poetry" in doc["tool"]:
        return doc["tool"]["poetry"]["version"]

    if "project" in doc:
        return doc["project"]["version"]

    raise KeyError("No version key found under [tool.poetry] or [project]")


# ---------------------------------------------------------------------------
# T1 — pyproject is 0.4.0
# ---------------------------------------------------------------------------


def test_t1_pyproject_version_is_040():
    r"""``tool.poetry.version`` (or ``project.version``) must equal ``"0.4.0"``."""
    version = _read_pyproject_version()
    assert version == "0.4.0", (
        f"pyproject.toml version is {version!r}, expected '0.4.0'"
    )


# ---------------------------------------------------------------------------
# T2 — DOMAIN version matches pyproject
# ---------------------------------------------------------------------------


def test_t2_domain_version_lockstep():
    r"""DOMAIN["version"] must always stay in lockstep with pyproject.toml."""
    pyproject_version = _read_pyproject_version()
    assert DOMAIN["version"] == pyproject_version, (
        f"DOMAIN['version']={DOMAIN['version']!r} != pyproject={pyproject_version!r}"
    )


# ---------------------------------------------------------------------------
# T3 — CHANGELOG has [0.4.0] section at the top
# ---------------------------------------------------------------------------


def test_t3_changelog_has_040_section_at_top():
    r"""``## [0.4.0]`` must be the first release header in CHANGELOG.md."""
    with open("CHANGELOG.md") as f:
        lines = f.readlines()

    release_lines = [
        (i, line.strip())
        for i, line in enumerate(lines, start=1)
        if line.strip().startswith("## [")
    ]

    assert release_lines, "CHANGELOG.md contains no release headers (## [x.y.z])"

    first_line_no, first_header = release_lines[0]
    assert first_header.startswith("## [0.4.0]"), (
        f"Expected top release header to be '## [0.4.0]', found {first_header!r} "
        f"at line {first_line_no}"
    )


# ---------------------------------------------------------------------------
# T4 — CHANGELOG [0.4.0] block covers Bundle-1 critical items
# ---------------------------------------------------------------------------


def test_t4_changelog_040_has_required_content():
    r"""The [0.4.0] CHANGELOG block must mention every critical Bundle-1 item."""
    with open("CHANGELOG.md") as f:
        content = f.read()

    start = content.find("## [0.4.0]")
    assert start != -1, "CHANGELOG.md missing ## [0.4.0] section"

    # Slice up to the next release header or EOF
    next_header = content.find("\n## [", start + 1)
    block = content[start:next_header] if next_header != -1 else content[start:]

    required = [
        "Ed25519",
        "EIP-712",
        "did:key",
        "eth-account >=0.10.0,<0.14.0",
        "base58",
        "amount_wei",
        "payload_json",
        "canonical_signed_bytes",
        "ensure_clerk_keys",
    ]
    missing = [s for s in required if s not in block]
    assert not missing, (
        f"CHANGELOG [0.4.0] block missing required substrings: {missing}"
    )


# ---------------------------------------------------------------------------
# T5 — full pytest run passes, no skips introduced by Bundle 1
# ---------------------------------------------------------------------------


def test_t5_no_pytest_mark_skip():
    r"""No ``pytest.mark.skip`` decorators may exist anywhere under ``test/``."""
    result = subprocess.run(
        [
            "grep",
            "-rE",
            "--include=*.py",
            r"pytest\.mark\.skip\b",
            "test/",
        ],
        capture_output=True,
        text=True,
    )
    # Filter out matches from this file itself (docstrings / code contain the
    # literal search string) and from __pycache__ binaries.
    self_name = os.path.basename(__file__)
    lines = [
        line
        for line in result.stdout.splitlines()
        if self_name not in line and "__pycache__" not in line
    ]
    assert not lines, "Forbidden pytest.mark.skip found in test/:\n" + "\n".join(lines)


def test_t5_full_pytest_suite_passes():
    r"""``pytest -q test/`` must exit 0 with no failures.

    A guard env-var prevents infinite recursion when this test spawns a
    subprocess that also tries to run itself.
    """
    if os.environ.get("PYTEST_IN_SUBPROCESS"):
        pytest.skip("Skipping recursive subprocess invocation")

    env = os.environ.copy()
    env["PYTEST_IN_SUBPROCESS"] = "1"

    result = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "test/"],
        capture_output=True,
        text=True,
        env=env,
    )
    assert result.returncode == 0, (
        f"pytest -q test/ failed (exit {result.returncode}):\n"
        f"--- stdout ---\n{result.stdout}\n"
        f"--- stderr ---\n{result.stderr}"
    )


# ---------------------------------------------------------------------------
# T6 — ruff clean
# ---------------------------------------------------------------------------


def test_t6_ruff_check_clean():
    r"""``ruff check oasis/ test/`` must exit 0."""
    result = subprocess.run(
        ["ruff", "check", "oasis/", "test/"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (
        f"ruff check failed:\n{result.stdout}\n{result.stderr}"
    )


def test_t6_ruff_format_produces_zero_diff():
    r"""``ruff format --diff`` must be empty (code already formatted)."""
    result = subprocess.run(
        ["ruff", "format", "--diff", "oasis/", "test/"],
        capture_output=True,
        text=True,
    )
    assert result.stdout.strip() == "", (
        f"ruff format would produce changes:\n{result.stdout}"
    )
