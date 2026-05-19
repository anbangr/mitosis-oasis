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
r"""T1–T4: sanity suite for the spec_v097 test-infrastructure bootstrap.

T1  Package is collectable (4 tests, zero errors).
T2  governance_db fixture seeds default constitution with required params.
T3  adj_db fixture provisions empty adjudication schema tables.
T4  Spec constants are importable by module path.
"""
from __future__ import annotations

import sqlite3
import subprocess
import sys
from pathlib import Path


# ---------------------------------------------------------------------------
# T1 — Package collectable with sanity suite
# ---------------------------------------------------------------------------


def test_t1_package_collectable():
    r"""T1: pytest --collect-only -q exits 0 and reports 4 tests collected."""
    project_root = Path(__file__).parent.parent.parent
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "test/spec_v097/",
            "--collect-only",
            "-q",
        ],
        capture_output=True,
        text=True,
        cwd=str(project_root),
    )
    assert result.returncode == 0, (
        f"Collection exited non-zero:\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
    )
    assert "4 tests collected" in result.stdout, (
        f"Expected '4 tests collected' in stdout:\n{result.stdout}"
    )


# ---------------------------------------------------------------------------
# T2 — governance_db fixture seeds default constitution (RED: missing params)
# ---------------------------------------------------------------------------


def test_t2_governance_db_seeds_constitution(governance_db: sqlite3.Connection):
    r"""T2: seeded constitution includes all spec-required parameter names.

    Fails (red) until the schema seeder is updated to include
    ``fairness_minimum``, ``protocol_fee_bps``, and ``reputation_alpha``.
    """
    rows = governance_db.execute(
        "SELECT param_name FROM constitution"
    ).fetchall()
    names = {r["param_name"] for r in rows}
    required = {
        "quorum_threshold",
        "fairness_minimum",
        "protocol_fee_bps",
        "reputation_alpha",
    }
    missing = required - names
    assert not missing, (
        f"Constitution missing spec-required params: {sorted(missing)}"
    )


# ---------------------------------------------------------------------------
# T3 — adj_db fixture provisions empty adjudication schema
# ---------------------------------------------------------------------------


def test_t3_adj_db_provisions_empty_schema(adj_db: sqlite3.Connection):
    r"""T3: adjudication DB has required tables, each with zero rows."""
    table_rows = adj_db.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()
    tables = {r["name"] for r in table_rows}
    required = {"agent_balance", "treasury", "adjudication_decision"}
    missing = required - tables
    assert not missing, f"Adjudication DB missing tables: {sorted(missing)}"

    for table in required:
        count = adj_db.execute(
            f"SELECT COUNT(*) AS cnt FROM {table}"  # noqa: S608
        ).fetchone()
        assert count["cnt"] == 0, (
            f"Expected {table!r} to be empty; found {count['cnt']} row(s)"
        )


# ---------------------------------------------------------------------------
# T4 — Spec constants are importable by name
# ---------------------------------------------------------------------------


def test_t4_spec_constants_importable():
    r"""T4: SPEC_QUORUM_THRESHOLD is 0.60 and importable via module path."""
    from test.spec_v097.conftest import SPEC_QUORUM_THRESHOLD  # noqa: PLC0415

    assert SPEC_QUORUM_THRESHOLD == 0.60, (
        f"SPEC_QUORUM_THRESHOLD: expected 0.60, got {SPEC_QUORUM_THRESHOLD}"
    )
