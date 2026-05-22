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
"""Milestone-based legislative-session trigger (spec leg §2.2).

Fires every ``milestone_round_interval`` (default 20) execution rounds.
A round is one settled task. The scheduler queries the ``settlement``
table (execution branch) to count rounds.
"""

from __future__ import annotations

import sqlite3
import uuid
from pathlib import Path


def should_fire(
    *,
    current_round: int,
    last_session_round: int,
    interval: int,
) -> bool:
    """Return True iff a milestone session is due."""
    if current_round < interval:
        return False
    return (current_round - last_session_round) >= interval


def fire_milestone_session(
    *,
    round_number: int,
    db_path: str | Path,
) -> str:
    """Create a new legislative_session with trigger='milestone'."""
    session_id = f"milestone-{uuid.uuid4().hex[:12]}"
    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute(
            "INSERT INTO legislative_session "
            "(session_id, state, trigger, mission_budget_cap) "
            "VALUES (?, 'SESSION_INIT', 'milestone', ?)",
            (session_id, float(round_number)),
        )
        conn.commit()
    finally:
        conn.close()
    return session_id


def get_current_round(*, exec_db_path: str | Path) -> int:
    """Count settled tasks = number of rounds."""
    conn = sqlite3.connect(str(exec_db_path))
    try:
        return conn.execute("SELECT COUNT(*) FROM settlement").fetchone()[0]
    finally:
        conn.close()


def get_last_milestone_round(*, gov_db_path: str | Path) -> int:
    """Get the round number of the most recent milestone-triggered session.

    Stored in ``mission_budget_cap`` (float) for simplicity — see
    ``fire_milestone_session``. Returns 0 when no milestone sessions
    exist yet, or when the stored value cannot be parsed.
    """
    conn = sqlite3.connect(str(gov_db_path))
    try:
        # Use MAX(mission_budget_cap) since round numbers are monotonic and
        # multiple rows can share a single CURRENT_TIMESTAMP second.
        row = conn.execute(
            "SELECT MAX(mission_budget_cap) FROM legislative_session "
            "WHERE trigger = 'milestone'"
        ).fetchone()
        if row is None or row[0] is None:
            return 0
        try:
            return int(row[0])
        except (ValueError, TypeError):
            return 0
    finally:
        conn.close()
