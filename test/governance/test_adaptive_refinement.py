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
"""Unit tests for adaptive_refinement (Bundle 5 Phase 6.1)."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from oasis.governance.adaptive_refinement import (
    get_iteration_budget,
    on_task_failed,
    should_refine,
    trigger_re_legislation,
)
from oasis.governance.schema import create_governance_tables


@pytest.fixture
def gov_db(tmp_path: Path) -> str:
    db = tmp_path / "g.db"
    create_governance_tables(str(db))
    return str(db)


def test_iteration_budget_starts_at_zero(gov_db: str) -> None:
    """T1: with no sessions, the budget for any task is 0."""
    assert get_iteration_budget(parent_task_id="t1", db_path=gov_db) == 0


def test_should_refine_true_below_budget(gov_db: str) -> None:
    """T2: 0 iterations used, budget = 3 → refinement allowed."""
    assert should_refine(parent_task_id="t1", db_path=gov_db, max_iterations=3) is True


def test_trigger_creates_session_with_iteration_one(gov_db: str) -> None:
    """T3: first call creates a session with iteration=1."""
    session_id = trigger_re_legislation(parent_task_id="t1", db_path=gov_db)
    assert session_id.startswith("refine-")
    conn = sqlite3.connect(gov_db)
    try:
        row = conn.execute(
            "SELECT trigger, parent_task_id, iteration FROM legislative_session "
            "WHERE session_id = ?",
            (session_id,),
        ).fetchone()
    finally:
        conn.close()
    assert row == ("adaptive_refinement", "t1", 1)


def test_budget_exhausted_at_three(gov_db: str) -> None:
    """T4: after 3 refinements, should_refine returns False."""
    for _ in range(3):
        trigger_re_legislation(parent_task_id="t-loop", db_path=gov_db)
    assert get_iteration_budget(parent_task_id="t-loop", db_path=gov_db) == 3
    assert (
        should_refine(parent_task_id="t-loop", db_path=gov_db, max_iterations=3)
        is False
    )


def test_independent_per_task_budgets(gov_db: str) -> None:
    """T5: exhausting t-a does not affect t-b's budget."""
    for _ in range(3):
        trigger_re_legislation(parent_task_id="t-a", db_path=gov_db)
    assert (
        should_refine(parent_task_id="t-a", db_path=gov_db, max_iterations=3) is False
    )
    assert should_refine(parent_task_id="t-b", db_path=gov_db, max_iterations=3) is True


def test_iteration_increments_monotonically(gov_db: str) -> None:
    """Each call to trigger_re_legislation increments iteration by 1."""
    iterations = []
    for _ in range(3):
        sid = trigger_re_legislation(parent_task_id="t1", db_path=gov_db)
        conn = sqlite3.connect(gov_db)
        try:
            it = conn.execute(
                "SELECT iteration FROM legislative_session WHERE session_id = ?",
                (sid,),
            ).fetchone()[0]
            iterations.append(it)
        finally:
            conn.close()
    assert iterations == [1, 2, 3]


def test_on_task_failed_creates_child_session(gov_db: str) -> None:
    """on_task_failed returns the new child session_id when budget allows."""
    session_id = on_task_failed(task_id="t1", gov_db_path=gov_db)
    assert session_id is not None
    assert session_id.startswith("refine-")


def test_on_task_failed_returns_none_when_exhausted(gov_db: str) -> None:
    """on_task_failed returns None once the budget is spent."""
    for _ in range(3):
        on_task_failed(task_id="t-loop", gov_db_path=gov_db, max_iterations=3)
    assert (
        on_task_failed(task_id="t-loop", gov_db_path=gov_db, max_iterations=3) is None
    )


def test_non_adaptive_sessions_dont_count(gov_db: str) -> None:
    """Sessions with other triggers (manual, milestone, petition) don't
    count against the adaptive budget for a given task."""
    conn = sqlite3.connect(gov_db)
    try:
        for trig in ("manual", "milestone", "petition"):
            conn.execute(
                "INSERT INTO legislative_session "
                "(session_id, state, trigger, parent_task_id, iteration) "
                "VALUES (?, 'SESSION_INIT', ?, ?, ?)",
                (f"sess-{trig}", trig, "t1", 99),
            )
        conn.commit()
    finally:
        conn.close()
    # Despite iteration=99 on non-adaptive rows, the budget is 0.
    assert get_iteration_budget(parent_task_id="t1", db_path=gov_db) == 0
