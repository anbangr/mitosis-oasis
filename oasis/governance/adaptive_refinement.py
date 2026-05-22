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
"""Adaptive refinement loop (spec leg §1.10).

When an execution task transitions to FAILED, the governance layer creates
a new legislative session targeted at the failed subtask. Iteration is
capped at ``adaptive_iteration_budget`` (default 3) per task subtree.

Iteration count is tracked via ``legislative_session.parent_task_id`` +
``legislative_session.iteration`` (Bundle-5 columns). A child session
inherits the failed task's id and gets ``iteration = prior_max + 1``.
"""

from __future__ import annotations

import sqlite3
import uuid
from pathlib import Path


def get_iteration_budget(*, parent_task_id: str, db_path: str | Path) -> int:
    """Return the count of refinement iterations already spent on this task.

    Counts only sessions with ``trigger='adaptive_refinement'``.
    """
    conn = sqlite3.connect(str(db_path))
    try:
        row = conn.execute(
            "SELECT MAX(iteration) FROM legislative_session "
            "WHERE parent_task_id = ? AND trigger = 'adaptive_refinement'",
            (parent_task_id,),
        ).fetchone()
        return int(row[0]) if row and row[0] is not None else 0
    finally:
        conn.close()


def should_refine(
    *,
    parent_task_id: str,
    db_path: str | Path,
    max_iterations: int = 3,
) -> bool:
    """Return True iff iteration count is still below ``max_iterations``."""
    return (
        get_iteration_budget(parent_task_id=parent_task_id, db_path=db_path)
        < max_iterations
    )


def trigger_re_legislation(*, parent_task_id: str, db_path: str | Path) -> str:
    """Create a refinement child session and return its session_id.

    Caller is responsible for the budget check (use ``should_refine`` first).
    """
    iteration = get_iteration_budget(parent_task_id=parent_task_id, db_path=db_path) + 1
    session_id = f"refine-{uuid.uuid4().hex[:12]}"
    objective = f"Adaptive refinement of {parent_task_id} (iter {iteration})"
    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute(
            "INSERT INTO legislative_session "
            "(session_id, state, trigger, parent_task_id, iteration, "
            "failed_reason) "
            "VALUES (?, 'SESSION_INIT', 'adaptive_refinement', ?, ?, ?)",
            (session_id, parent_task_id, iteration, objective),
        )
        conn.commit()
    finally:
        conn.close()
    return session_id


def on_task_failed(
    *,
    task_id: str,
    gov_db_path: str | Path,
    max_iterations: int = 3,
) -> str | None:
    """Event-bus subscriber for ``task_failed``.

    Returns the child session_id, or ``None`` if the budget is exhausted.
    """
    if not should_refine(
        parent_task_id=task_id,
        db_path=gov_db_path,
        max_iterations=max_iterations,
    ):
        return None
    return trigger_re_legislation(parent_task_id=task_id, db_path=gov_db_path)
