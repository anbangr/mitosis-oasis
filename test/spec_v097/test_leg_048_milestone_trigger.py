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
"""Spec leg §2.2 — milestone trigger fires every milestone_round_interval rounds."""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from oasis.execution.schema import create_execution_tables
from oasis.governance.schema import create_governance_tables
from oasis.governance.scheduler.milestone_trigger import (
    fire_milestone_session,
    get_current_round,
    get_last_milestone_round,
    should_fire,
)


@pytest.fixture
def gov_db(tmp_path: Path) -> str:
    db = tmp_path / "g.db"
    create_governance_tables(str(db))
    return str(db)


@pytest.fixture
def exec_db(tmp_path: Path) -> str:
    db = tmp_path / "exec.db"
    create_execution_tables(str(db))
    return str(db)


def _seed_settlement(db_path: str, n: int) -> None:
    """Seed `n` settlement rows to represent `n` completed rounds."""
    conn = sqlite3.connect(db_path)
    for i in range(n):
        conn.execute(
            "INSERT INTO settlement "
            "(settlement_id, task_id, agent_did, base_reward, "
            "reputation_multiplier, final_reward, protocol_fee, "
            "insurance_fee) "
            "VALUES (?, ?, 'did:key:zAgent1', 10.0, 1.0, 10.0, 0.5, 0.5)",
            (f"settle-{i}", f"task-{i}"),
        )
    conn.commit()
    conn.close()


def test_t1_fires_at_round_20(exec_db: str, gov_db: str) -> None:
    """At round 20 with no prior milestone, the trigger fires."""
    _seed_settlement(exec_db, 20)
    current = get_current_round(exec_db_path=exec_db)
    last = get_last_milestone_round(gov_db_path=gov_db)
    assert current == 20
    assert last == 0
    assert should_fire(current_round=current, last_session_round=last, interval=20) is True


def test_t2_does_not_fire_before_interval(exec_db: str, gov_db: str) -> None:
    """At round 15 with interval 20, the trigger does NOT fire."""
    _seed_settlement(exec_db, 15)
    current = get_current_round(exec_db_path=exec_db)
    assert should_fire(current_round=current, last_session_round=0, interval=20) is False


def test_t3_fires_at_subsequent_multiples(gov_db: str) -> None:
    """After a milestone at round 20, the next fires at round 40."""
    fire_milestone_session(round_number=20, db_path=gov_db)
    last = get_last_milestone_round(gov_db_path=gov_db)
    assert last == 20
    assert should_fire(current_round=40, last_session_round=last, interval=20) is True
    assert should_fire(current_round=39, last_session_round=last, interval=20) is False


def test_t4_session_created_with_correct_trigger(gov_db: str) -> None:
    """fire_milestone_session inserts a row with trigger='milestone' and round metadata."""
    session_id = fire_milestone_session(round_number=20, db_path=gov_db)
    conn = sqlite3.connect(gov_db)
    row = conn.execute(
        "SELECT trigger, mission_budget_cap FROM legislative_session "
        "WHERE session_id = ?",
        (session_id,),
    ).fetchone()
    conn.close()
    assert row is not None
    assert row[0] == "milestone"
    assert int(row[1]) == 20
