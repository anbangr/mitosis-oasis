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
"""Scheduler module tests (Feature 7, Phase 1).

These tests verify ``start_scheduler`` and ``stop_scheduler`` in
``oasis.adjudication.scheduler``.  They MUST be red before the
implementation is written (TDD invariant).
"""

from __future__ import annotations

import asyncio
import logging
import sqlite3
import warnings
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from oasis.adjudication.schema import create_adjudication_tables
from oasis.governance.schema import create_governance_tables, seed_constitution


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def adj_db(tmp_path: Path) -> Path:
    """Fresh adjudication DB with full schema."""
    db_path = tmp_path / "adj.db"
    create_adjudication_tables(db_path)
    return db_path


@pytest.fixture()
def gov_db(tmp_path: Path) -> Path:
    """Fresh governance DB with full schema and constitution seeds."""
    db_path = tmp_path / "gov.db"
    create_governance_tables(db_path)
    seed_constitution(db_path)
    return db_path


@pytest.fixture()
def gov_db_pre_bundle2(tmp_path: Path) -> Path:
    """Governance DB missing the Bundle-2 constitution parameters."""
    db_path = tmp_path / "gov_pre_bundle2.db"
    create_governance_tables(db_path)
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA foreign_keys = ON")
    # Seed only pre-Bundle-2 params
    old_params = [
        ("voting_method", 1.0, "integer", "Voting method"),
        ("max_dag_depth", 10.0, "integer", "Maximum DAG depth"),
        ("max_dag_nodes", 50.0, "integer", "Maximum nodes per proposal DAG"),
    ]
    conn.executemany(
        "INSERT INTO constitution (param_name, param_value, param_type, description) "
        "VALUES (?, ?, ?, ?)",
        old_params,
    )
    conn.commit()
    conn.close()
    return db_path


@pytest.fixture()
def scheduler(adj_db: Path, gov_db: Path):
    """Yield a running scheduler; guarantee cleanup via stop_scheduler."""
    from oasis.adjudication.scheduler import start_scheduler, stop_scheduler

    s = start_scheduler(adj_db_path=str(adj_db), gov_db_path=str(gov_db))
    yield s
    stop_scheduler()


# ---------------------------------------------------------------------------
# T1 — Scheduler starts cleanly and registers both jobs
# ---------------------------------------------------------------------------


def test_scheduler_starts_and_registers_both_jobs(adj_db: Path, gov_db: Path) -> None:
    """T1: start_scheduler returns a running scheduler with both jobs registered."""
    from oasis.adjudication.scheduler import start_scheduler, stop_scheduler

    s = start_scheduler(adj_db_path=str(adj_db), gov_db_path=str(gov_db))
    try:
        assert s.running is True
        assert s.get_job("freeze_sweeper") is not None
        assert s.get_job("watchdog_scan") is not None
    finally:
        stop_scheduler()


# ---------------------------------------------------------------------------
# T2 — start_scheduler is idempotent
# ---------------------------------------------------------------------------


def test_start_scheduler_is_idempotent(adj_db: Path, gov_db: Path) -> None:
    """T2: Second call returns the same instance and does not duplicate jobs."""
    from oasis.adjudication.scheduler import start_scheduler, stop_scheduler

    s1 = start_scheduler(adj_db_path=str(adj_db), gov_db_path=str(gov_db))
    try:
        s2 = start_scheduler(adj_db_path=str(adj_db), gov_db_path=str(gov_db))
        assert s1 is s2
        jobs = s1.get_jobs()
        sweeper_jobs = [j for j in jobs if j.id == "freeze_sweeper"]
        watchdog_jobs = [j for j in jobs if j.id == "watchdog_scan"]
        assert len(sweeper_jobs) == 1
        assert len(watchdog_jobs) == 1
    finally:
        stop_scheduler()


# ---------------------------------------------------------------------------
# T3 — stop_scheduler shuts down cleanly
# ---------------------------------------------------------------------------


def test_stop_scheduler_shuts_down_cleanly(adj_db: Path, gov_db: Path) -> None:
    """T3: stop_scheduler clears the module global and allows fresh restart."""
    from oasis.adjudication.scheduler import (
        _scheduler,
        start_scheduler,
        stop_scheduler,
    )

    s1 = start_scheduler(adj_db_path=str(adj_db), gov_db_path=str(gov_db))
    stop_scheduler()
    assert _scheduler is None
    s2 = start_scheduler(adj_db_path=str(adj_db), gov_db_path=str(gov_db))
    try:
        assert s2 is not s1
        assert s2.running is True
    finally:
        stop_scheduler()


# ---------------------------------------------------------------------------
# T4 — Job wrappers swallow exceptions
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_job_wrappers_swallow_exceptions(
    adj_db: Path,
    gov_db: Path,
    monkeypatch,
    caplog,
) -> None:
    """T4: A failing sweeper job does not crash the scheduler."""
    from oasis.adjudication import freeze_sweeper
    from oasis.adjudication.scheduler import start_scheduler, stop_scheduler

    def _failing_sweep(*, db_path, max_duration_ms: int = 259_200_000) -> int:
        raise RuntimeError("forced sweep failure")

    monkeypatch.setattr(freeze_sweeper, "sweep_expired_freezes", _failing_sweep)

    caplog.set_level(logging.ERROR, logger="oasis.adjudication.scheduler")

    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        s = start_scheduler(adj_db_path=str(adj_db), gov_db_path=str(gov_db))
        try:
            # Force the sweeper job to run immediately
            job = s.get_job("freeze_sweeper")
            job.modify(next_run_time=datetime.now(timezone.utc))
            await asyncio.sleep(0.3)

            assert s.running is True

            error_records = [
                r
                for r in caplog.records
                if r.levelno == logging.ERROR
                and "forced sweep failure" in str(r.message)
            ]
            assert len(error_records) >= 1

            pending = [
                x
                for x in w
                if "pending" in str(x.message).lower() or "Future" in str(x.message)
            ]
            assert not pending, f"Unexpected pending-Future warnings: {pending}"
        finally:
            stop_scheduler()


# ---------------------------------------------------------------------------
# Edge case — Constitution missing new parameters → fallback defaults
# ---------------------------------------------------------------------------


def test_start_scheduler_fallback_when_constitution_params_missing(
    gov_db_pre_bundle2: Path,
    adj_db: Path,
) -> None:
    """start_scheduler falls back to defaults when Bundle-2 params are absent."""
    from oasis.adjudication.scheduler import start_scheduler, stop_scheduler

    s = start_scheduler(adj_db_path=str(adj_db), gov_db_path=str(gov_db_pre_bundle2))
    try:
        assert s.running is True
        # Jobs should still be registered even with fallback values
        assert s.get_job("freeze_sweeper") is not None
        assert s.get_job("watchdog_scan") is not None
    finally:
        stop_scheduler()


# ---------------------------------------------------------------------------
# Edge case — Lifespan wiring
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_lifespan_calls_scheduler_start_and_stop(monkeypatch) -> None:
    """The FastAPI lifespan calls start_scheduler on startup and stop_scheduler on shutdown."""
    from oasis import api as api_module
    from oasis.api import lifespan
    from fastapi import FastAPI

    saved = {
        "channel": api_module.channel,
        "platform": api_module.platform,
        "_platform_task": api_module._platform_task,
    }

    fake_platform = MagicMock()
    fake_platform.running = AsyncMock()
    monkeypatch.setattr("oasis.api.Channel", MagicMock)
    monkeypatch.setattr("oasis.api.Platform", lambda **kwargs: fake_platform)

    mock_start = MagicMock()
    mock_stop = MagicMock()
    monkeypatch.setattr("oasis.api.start_scheduler", mock_start)
    monkeypatch.setattr("oasis.api.stop_scheduler", mock_stop)

    app = FastAPI(lifespan=lifespan)
    try:
        async with lifespan(app):
            pass

        mock_start.assert_called_once()
        mock_stop.assert_called_once()
    finally:
        api_module.channel = saved["channel"]
        api_module.platform = saved["platform"]
        api_module._platform_task = saved["_platform_task"]
