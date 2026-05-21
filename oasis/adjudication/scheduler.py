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
"""Scheduler module — background jobs for freeze sweeper and watchdog."""

from __future__ import annotations

import asyncio
import logging
import sqlite3
import threading
from typing import Optional

from apscheduler.schedulers import SchedulerNotRunningError
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from oasis.adjudication import freeze_sweeper
from oasis.adjudication import watchdog

logger = logging.getLogger(__name__)

_scheduler: Optional[AsyncIOScheduler] = None


def start_scheduler(
    *, adj_db_path: str, gov_db_path: str, config=None
) -> AsyncIOScheduler:
    """Start the background scheduler with freeze-sweeper and watchdog jobs.

    Idempotent — returns the existing running scheduler if already started.
    """
    global _scheduler

    if _scheduler is not None and _scheduler.running:
        return _scheduler

    # Read constitution params via direct SQLite query (no ORM)
    params: dict[str, float] = {}
    try:
        conn = sqlite3.connect(gov_db_path)
        conn.row_factory = sqlite3.Row
        try:
            rows = conn.execute(
                "SELECT param_name, param_value FROM constitution "
                "WHERE param_name IN (?, ?, ?)",
                (
                    "max_freeze_duration_ms",
                    "watchdog_window_days",
                    "watchdog_zscore_threshold",
                ),
            ).fetchall()
            params = {row["param_name"]: row["param_value"] for row in rows}
        finally:
            conn.close()
    except sqlite3.Error as exc:
        logger.warning("Could not read constitution params: %s", exc)

    max_freeze_duration_ms = int(params.get("max_freeze_duration_ms", 259_200_000))
    watchdog_window_days = int(params.get("watchdog_window_days", 30))
    watchdog_zscore_threshold = float(params.get("watchdog_zscore_threshold", 2.0))

    # Determine event loop — use the running loop if available, otherwise spin
    # up a background thread with its own loop so sync tests also work.
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        t = threading.Thread(target=loop.run_forever, daemon=True)
        t.start()

    _scheduler = AsyncIOScheduler(event_loop=loop)

    def _sweep_job() -> None:
        try:
            freeze_sweeper.sweep_expired_freezes(
                db_path=adj_db_path, max_duration_ms=max_freeze_duration_ms
            )
        except Exception as exc:
            logger.error("freeze_sweeper job failed: %s", exc, exc_info=True)

    def _watchdog_job() -> None:
        try:
            watchdog.scan_anomalies(
                db_path=adj_db_path,
                window_days=watchdog_window_days,
                zscore_threshold=watchdog_zscore_threshold,
            )
        except Exception as exc:
            logger.error("watchdog_scan job failed: %s", exc, exc_info=True)

    _scheduler.add_job(
        _sweep_job,
        "interval",
        minutes=5,
        id="freeze_sweeper",
        replace_existing=True,
    )
    _scheduler.add_job(
        _watchdog_job,
        "interval",
        hours=1,
        id="watchdog_scan",
        replace_existing=True,
    )

    _scheduler.start()
    return _scheduler


def stop_scheduler() -> None:
    """Shut down the background scheduler and clear the module global."""
    global _scheduler
    if _scheduler is not None:
        try:
            _scheduler.shutdown(wait=False)
        except SchedulerNotRunningError:
            pass
    _scheduler = None
