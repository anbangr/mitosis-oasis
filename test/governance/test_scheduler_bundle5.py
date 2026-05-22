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
"""Bundle 5 Phase 7.1 — milestone_trigger job wired into adjudication scheduler."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from oasis.adjudication.schema import create_adjudication_tables
from oasis.adjudication.scheduler import start_scheduler, stop_scheduler
from oasis.execution.schema import create_execution_tables
from oasis.governance.schema import create_governance_tables, seed_constitution


@pytest.fixture
def dbs(tmp_path: Path):
    gov = tmp_path / "gov.db"
    create_governance_tables(str(gov))
    seed_constitution(str(gov))
    adj = tmp_path / "adj.db"
    create_adjudication_tables(str(adj))
    execdb = tmp_path / "exec.db"
    create_execution_tables(str(execdb))
    yield {"gov": str(gov), "adj": str(adj), "exec": str(execdb)}


@pytest.fixture(autouse=True)
def _stop_scheduler_between_tests():
    yield
    stop_scheduler()


def _seed_settlement(db_path: str, n: int) -> None:
    """Seed n settlement rows to represent n completed rounds."""
    conn = sqlite3.connect(db_path)
    for i in range(n):
        conn.execute(
            "INSERT INTO settlement "
            "(settlement_id, task_id, agent_did, base_reward, "
            "reputation_multiplier, final_reward, protocol_fee, "
            "insurance_fee) "
            "VALUES (?, ?, 'did:key:zA', 10.0, 1.0, 10.0, 0.5, 0.5)",
            (f"settle-{i}", f"task-{i}"),
        )
    conn.commit()
    conn.close()


def test_t1_milestone_job_registered(dbs):
    """T1: start_scheduler() registers a job with id 'milestone_trigger'."""
    sched = start_scheduler(
        adj_db_path=dbs["adj"],
        gov_db_path=dbs["gov"],
        exec_db_path=dbs["exec"],
    )
    job_ids = {job.id for job in sched.get_jobs()}
    assert "milestone_trigger" in job_ids


def test_t1b_milestone_job_skipped_when_no_exec_db(dbs):
    """When exec_db_path is None, the milestone job is NOT registered
    (preserves backward compatibility)."""
    sched = start_scheduler(adj_db_path=dbs["adj"], gov_db_path=dbs["gov"])
    job_ids = {job.id for job in sched.get_jobs()}
    assert "milestone_trigger" not in job_ids


def test_t2_milestone_job_fires_at_interval(dbs):
    """T2: with 20 settlements and no prior milestone session, invoking the
    job creates a new session with trigger='milestone'."""
    _seed_settlement(dbs["exec"], 20)
    sched = start_scheduler(
        adj_db_path=dbs["adj"],
        gov_db_path=dbs["gov"],
        exec_db_path=dbs["exec"],
    )
    job = sched.get_job("milestone_trigger")
    # Invoke the registered callable directly.
    job.func()
    conn = sqlite3.connect(dbs["gov"])
    rows = conn.execute(
        "SELECT session_id, trigger FROM legislative_session "
        "WHERE trigger = 'milestone'"
    ).fetchall()
    conn.close()
    assert len(rows) == 1
    assert rows[0][1] == "milestone"


def test_t3_milestone_job_idempotent_within_interval(dbs):
    """T3: running the job a second time at the same round does not create
    a duplicate session."""
    _seed_settlement(dbs["exec"], 20)
    sched = start_scheduler(
        adj_db_path=dbs["adj"],
        gov_db_path=dbs["gov"],
        exec_db_path=dbs["exec"],
    )
    job = sched.get_job("milestone_trigger")
    job.func()
    job.func()  # Second invocation must NOT create a second session.
    conn = sqlite3.connect(dbs["gov"])
    count = conn.execute(
        "SELECT COUNT(*) FROM legislative_session WHERE trigger = 'milestone'"
    ).fetchone()[0]
    conn.close()
    assert count == 1


def test_t4_job_does_not_fire_with_empty_settlement(dbs):
    """Edge: 0 settlements → round 0 → does not fire."""
    sched = start_scheduler(
        adj_db_path=dbs["adj"],
        gov_db_path=dbs["gov"],
        exec_db_path=dbs["exec"],
    )
    sched.get_job("milestone_trigger").func()
    conn = sqlite3.connect(dbs["gov"])
    count = conn.execute(
        "SELECT COUNT(*) FROM legislative_session WHERE trigger = 'milestone'"
    ).fetchone()[0]
    conn.close()
    assert count == 0


def test_t5_milestone_job_swallows_exceptions(dbs, monkeypatch):
    """Edge: an exception inside the milestone job is logged but does not
    propagate (would otherwise crash the scheduler)."""
    sched = start_scheduler(
        adj_db_path=dbs["adj"],
        gov_db_path=dbs["gov"],
        exec_db_path=dbs["exec"],
    )

    def _explode(**_kwargs):
        raise RuntimeError("boom")

    # Patch the get_current_round import inside the scheduler module so the
    # closure picks up the broken function.
    import oasis.adjudication.scheduler as sched_mod
    import oasis.governance.scheduler.milestone_trigger as mt

    monkeypatch.setattr(mt, "get_current_round", _explode)
    monkeypatch.setattr(sched_mod, "logger", sched_mod.logger)  # no-op, keeps ref

    # Should not raise.
    sched.get_job("milestone_trigger").func()
