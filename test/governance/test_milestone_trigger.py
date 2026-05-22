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
"""Unit tests for milestone_trigger (Bundle 5 Phase 4.1)."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from oasis.governance.scheduler.milestone_trigger import (
    fire_milestone_session,
    get_last_milestone_round,
    should_fire,
)
from oasis.governance.schema import create_governance_tables


@pytest.fixture
def gov_db(tmp_path: Path) -> str:
    db = tmp_path / "g.db"
    create_governance_tables(str(db))
    return str(db)


def test_should_fire_at_interval_boundary() -> None:
    assert should_fire(current_round=20, last_session_round=0, interval=20) is True


def test_should_not_fire_below_interval() -> None:
    assert should_fire(current_round=15, last_session_round=0, interval=20) is False


def test_should_fire_at_subsequent_multiples() -> None:
    assert should_fire(current_round=40, last_session_round=20, interval=20) is True


def test_should_not_fire_when_gap_under_interval() -> None:
    assert should_fire(current_round=30, last_session_round=20, interval=20) is False


def test_should_not_fire_round_one_with_interval_twenty() -> None:
    assert should_fire(current_round=1, last_session_round=0, interval=20) is False


def test_fire_milestone_session_inserts_row_with_trigger(gov_db: str) -> None:
    session_id = fire_milestone_session(round_number=20, db_path=gov_db)
    assert session_id.startswith("milestone-")
    conn = sqlite3.connect(gov_db)
    row = conn.execute(
        "SELECT session_id, state, trigger, mission_budget_cap "
        "FROM legislative_session WHERE session_id = ?",
        (session_id,),
    ).fetchone()
    conn.close()
    assert row is not None
    assert row[0] == session_id
    assert row[1] == "SESSION_INIT"
    assert row[2] == "milestone"
    assert row[3] == 20.0


def test_get_last_milestone_round_returns_zero_when_no_sessions(gov_db: str) -> None:
    assert get_last_milestone_round(gov_db_path=gov_db) == 0


def test_get_last_milestone_round_returns_most_recent(gov_db: str) -> None:
    fire_milestone_session(round_number=20, db_path=gov_db)
    fire_milestone_session(round_number=40, db_path=gov_db)
    assert get_last_milestone_round(gov_db_path=gov_db) == 40
