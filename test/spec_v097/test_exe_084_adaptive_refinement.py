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
"""Spec leg §1.10 — adaptive refinement loop with per-subtask iteration budget."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from oasis.governance.adaptive_refinement import (
    get_iteration_budget,
    should_refine,
    trigger_re_legislation,
)
from oasis.governance.schema import create_governance_tables


@pytest.fixture
def gov_db(tmp_path: Path) -> str:
    db = tmp_path / "g.db"
    create_governance_tables(str(db))
    return str(db)


def test_t1_budget_starts_at_zero(gov_db: str) -> None:
    """T1: a task with no prior adaptive sessions has budget 0."""
    assert get_iteration_budget(parent_task_id="t1", db_path=gov_db) == 0


def test_t2_refine_allowed_below_budget(gov_db: str) -> None:
    """T2: budget=0, max=3 → refinement allowed."""
    assert should_refine(parent_task_id="t1", db_path=gov_db, max_iterations=3) is True


def test_t3_child_session_iteration_one(gov_db: str) -> None:
    """T3: first refinement creates a session with iteration=1."""
    sid = trigger_re_legislation(parent_task_id="t1", db_path=gov_db)
    conn = sqlite3.connect(gov_db)
    try:
        row = conn.execute(
            "SELECT trigger, parent_task_id, iteration FROM legislative_session "
            "WHERE session_id = ?",
            (sid,),
        ).fetchone()
    finally:
        conn.close()
    assert row == ("adaptive_refinement", "t1", 1)


def test_t4_budget_exhausted_at_three(gov_db: str) -> None:
    """T4: after 3 iterations the budget blocks further refinement."""
    for _ in range(3):
        trigger_re_legislation(parent_task_id="t-loop", db_path=gov_db)
    assert (
        should_refine(parent_task_id="t-loop", db_path=gov_db, max_iterations=3)
        is False
    )


def test_t5_independent_per_task_budgets(gov_db: str) -> None:
    """T5: exhausting one task does not affect another task's budget."""
    for _ in range(3):
        trigger_re_legislation(parent_task_id="t-a", db_path=gov_db)
    assert should_refine(parent_task_id="t-b", db_path=gov_db, max_iterations=3) is True
