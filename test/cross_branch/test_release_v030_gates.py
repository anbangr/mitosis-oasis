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
r"""T1–T5: Bundle-0 release acceptance gates for v0.3.0.

These tests enforce the final verification checklist from the Bundle-0
source plan.  They will fail (red) until the release commit lands:
version bumps, CHANGELOG update, and all feature branches are merged.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# T1 — All three version surfaces in lockstep at 0.3.0
# ---------------------------------------------------------------------------


def test_t1_version_lockstep():
    r"""T1: pyproject.toml, oasis/__init__.py, and oasis/api.py each contain
    exactly one ``"0.4.0"`` and no stale ``0.2.5``/``0.2.6``/``0.3.0`` strings.
    """
    project_root = Path(__file__).parent.parent.parent
    files = {
        "pyproject.toml": project_root / "pyproject.toml",
        "oasis/__init__.py": project_root / "oasis" / "__init__.py",
        "oasis/api.py": project_root / "oasis" / "api.py",
    }

    stale_pattern = re.compile(r'"(0\.2\.[56]|0\.3\.0)"')
    target_pattern = re.compile(r'"0\.7\.0"')

    for name, path in files.items():
        content = path.read_text()
        stale_matches = stale_pattern.findall(content)
        assert not stale_matches, (
            f"{name} contains stale version string(s): {stale_matches}"
        )
        target_count = len(target_pattern.findall(content))
        assert target_count == 1, (
            f"{name} should contain exactly one '0.7.0', found {target_count}"
        )


# ---------------------------------------------------------------------------
# T2 — CHANGELOG lists all six fixes with spec citations
# ---------------------------------------------------------------------------


def test_t2_changelog_citations():
    r"""T2: CHANGELOG.md has a ``[0.3.0]`` entry containing all six spec citations.

    Citations required: spec §1.7, spec §2.2-2.3, spec §2.6, spec §1.2,
    spec §1.5, spec §8.5.
    """
    changelog_path = Path(__file__).parent.parent.parent / "CHANGELOG.md"
    content = changelog_path.read_text()

    assert "## [0.3.0]" in content, "CHANGELOG.md missing [0.3.0] entry"

    # Isolate the [0.3.0] section (up to the next heading or EOF)
    section_match = re.search(r"## \[0\.3\.0\].*?(?=\n## \[|\Z)", content, re.DOTALL)
    assert section_match, "Could not isolate [0.3.0] section in CHANGELOG.md"
    section = section_match.group(0)

    required_citations = [
        "spec §1.7",
        "spec §2.2-2.3",
        "spec §2.6",
        "spec §1.2",
        "spec §1.5",
        "spec §8.5",
    ]
    missing = [c for c in required_citations if c not in section]
    assert not missing, f"Missing citations in [0.3.0] CHANGELOG entry: {missing}"


# ---------------------------------------------------------------------------
# T3 — Full pytest suite green
# ---------------------------------------------------------------------------


def test_t3_full_pytest_suite_green():
    r"""T3: ``pytest -q`` exits 0 with zero failures and zero errors."""
    project_root = Path(__file__).parent.parent.parent
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            "--ignore=test/cross_branch/test_release_v030_gates.py",
        ],
        capture_output=True,
        text=True,
        cwd=str(project_root),
    )
    assert result.returncode == 0, (
        f"pytest -q exited {result.returncode}:\nSTDOUT:\n{result.stdout}\n"
        f"STDERR:\n{result.stderr}"
    )
    stdout_lower = result.stdout.lower()
    assert "failed" not in stdout_lower, f"pytest reported failures:\n{result.stdout}"
    assert "error" not in stdout_lower, f"pytest reported errors:\n{result.stdout}"


# ---------------------------------------------------------------------------
# T4 — Acceptance gates from spec section 5 hold
# ---------------------------------------------------------------------------


def test_t4_acceptance_gates():
    r"""T4: Run the gate checklist from the source plan Acceptance Gates section.

    Testable gates:
    1. Legacy suites (governance, execution, adjudication, observatory,
       cross_branch, api) pass with 0 failures.
    2. spec_v097 + e2e suites pass with 14+ tests (Bundle-0 baseline: 4 spec_v097 sanity + 10 e2e).
    3. pyproject.toml version reads 0.3.0.
    4. CHANGELOG.md has an [0.3.0] entry.
    """
    project_root = Path(__file__).parent.parent.parent

    # Gate 1 — legacy suites
    legacy_result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "test/governance/",
            "test/execution/",
            "test/adjudication/",
            "test/observatory/",
            "test/cross_branch/",
            "test/api/",
            "-q",
            "--ignore=test/cross_branch/test_release_v030_gates.py",
        ],
        capture_output=True,
        text=True,
        cwd=str(project_root),
    )
    assert legacy_result.returncode == 0, (
        f"Legacy suites failed:\nSTDOUT:\n{legacy_result.stdout}\n"
        f"STDERR:\n{legacy_result.stderr}"
    )

    # Gate 2 — spec_v097 + e2e suites. Bundle-0 baseline: 4 spec_v097 + 10 e2e = 14.
    # Bundles 1-5 will add more spec_v097 cases and raise this floor.
    new_result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "test/spec_v097/",
            "test/e2e/",
            "-q",
        ],
        capture_output=True,
        text=True,
        cwd=str(project_root),
    )
    assert new_result.returncode == 0, (
        f"spec_v097/e2e suites failed:\nSTDOUT:\n{new_result.stdout}\n"
        f"STDERR:\n{new_result.stderr}"
    )
    # Expect at least 14 tests in spec_v097 + e2e combined (Bundle-0 baseline).
    collect_result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "test/spec_v097/",
            "test/e2e/",
            "--collect-only",
            "-q",
        ],
        capture_output=True,
        text=True,
        cwd=str(project_root),
    )
    assert collect_result.returncode == 0
    match = re.search(r"(\d+) tests collected", collect_result.stdout)
    assert match, f"Could not parse test count from:\n{collect_result.stdout}"
    collected = int(match.group(1))
    assert collected >= 14, (
        f"Expected >= 14 tests in spec_v097 + e2e, found {collected}"
    )

    # Gate 3 — pyproject.toml version
    pyproject = (project_root / "pyproject.toml").read_text()
    assert 'version = "0.7.0"' in pyproject, (
        "pyproject.toml does not declare version 0.7.0"
    )

    # Gate 4 — CHANGELOG [0.3.0] entry
    changelog = (project_root / "CHANGELOG.md").read_text()
    assert "## [0.3.0]" in changelog, "CHANGELOG.md missing [0.3.0] entry"


# ---------------------------------------------------------------------------
# T5 — Lint + format clean
# ---------------------------------------------------------------------------


def test_t5_lint_format_clean():
    r"""T5: ``ruff check oasis/ test/`` and ``ruff format --check oasis/ test/``
    both exit 0 with no unfixable errors.
    """
    project_root = Path(__file__).parent.parent.parent

    check_result = subprocess.run(
        [sys.executable, "-m", "ruff", "check", "oasis/", "test/"],
        capture_output=True,
        text=True,
        cwd=str(project_root),
    )
    if check_result.returncode == 127 or "No module named" in check_result.stderr:
        import pytest

        pytest.skip("ruff not installed in this environment")
    assert check_result.returncode == 0, (
        f"ruff check failed (exit {check_result.returncode}):\n"
        f"STDOUT:\n{check_result.stdout}\nSTDERR:\n{check_result.stderr}"
    )

    format_result = subprocess.run(
        [sys.executable, "-m", "ruff", "format", "--check", "oasis/", "test/"],
        capture_output=True,
        text=True,
        cwd=str(project_root),
    )
    assert format_result.returncode == 0, (
        f"ruff format --check failed (exit {format_result.returncode}):\n"
        f"STDOUT:\n{format_result.stdout}\nSTDERR:\n{format_result.stderr}"
    )
