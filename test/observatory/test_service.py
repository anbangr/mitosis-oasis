# Copyright 2023 The CAMEL-AI.org. All Rights Reserved.
#
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
"""Unit tests for ObservatoryService (RP2-C).

Tests the service layer directly (no HTTP), using a temp SQLite DB.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from oasis.observatory.service import ObservatoryService


@pytest.fixture()
def service(tmp_path: Path) -> ObservatoryService:
    """ObservatoryService backed by a fresh temp DB."""
    db = tmp_path / "obs_service_test.db"
    return ObservatoryService(str(db))


@pytest.fixture()
def populated_service(tmp_path: Path) -> ObservatoryService:
    """ObservatoryService with all observatory tables + sample data."""
    db = tmp_path / "obs_populated.db"
    svc = ObservatoryService(str(db))

    conn = sqlite3.connect(str(db))
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS legislative_session (
            session_id TEXT, state TEXT, created_at TEXT
        );
        CREATE TABLE IF NOT EXISTS agent_registry (
            agent_did TEXT PRIMARY KEY, display_name TEXT,
            agent_type TEXT, reputation_score REAL
        );
        CREATE TABLE IF NOT EXISTS agent_balance (
            agent_did TEXT, total_balance REAL,
            available_balance REAL, locked_stake REAL
        );
        CREATE TABLE IF NOT EXISTS task_assignment (
            node_id TEXT, agent_did TEXT, status TEXT
        );
        CREATE TABLE IF NOT EXISTS treasury (
            entry_id INTEGER PRIMARY KEY AUTOINCREMENT,
            entry_type TEXT, amount REAL, balance_after REAL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS guardian_alert (alert_id TEXT PRIMARY KEY);
        CREATE TABLE IF NOT EXISTS reputation_ledger (
            entry_id INTEGER PRIMARY KEY AUTOINCREMENT,
            agent_did TEXT, old_score REAL, new_score REAL,
            performance_score REAL, reason TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS event_log (
            event_id TEXT PRIMARY KEY,
            event_type TEXT, timestamp TEXT,
            session_id TEXT, agent_did TEXT,
            payload TEXT, sequence_number INTEGER
        );
    """)

    conn.execute(
        "INSERT INTO agent_registry VALUES ('did:mock:agent-1', 'Alice', 'producer', 0.8)"
    )
    conn.execute(
        "INSERT INTO agent_registry VALUES ('did:mock:agent-2', 'Bob', 'consumer', 0.6)"
    )
    conn.execute(
        "INSERT INTO agent_balance VALUES ('did:mock:agent-1', 100.0, 80.0, 20.0)"
    )
    conn.execute("INSERT INTO treasury VALUES (NULL, 'reward', 10.0, 110.0, CURRENT_TIMESTAMP)")
    conn.execute(
        "INSERT INTO legislative_session VALUES ('sess-1', 'OPEN', CURRENT_TIMESTAMP)"
    )
    conn.execute(
        "INSERT INTO legislative_session VALUES ('sess-2', 'CLOSED', CURRENT_TIMESTAMP)"
    )
    conn.execute(
        "INSERT INTO reputation_ledger VALUES "
        "(NULL, 'did:mock:agent-1', 0.7, 0.8, 0.9, 'good work', CURRENT_TIMESTAMP)"
    )
    conn.execute(
        "INSERT INTO event_log VALUES "
        "('ev-1', 'session.open', CURRENT_TIMESTAMP, 'sess-1', NULL, '{}', 1)"
    )
    conn.execute(
        "INSERT INTO task_assignment VALUES ('node-1', 'did:mock:agent-1', 'settled')"
    )
    conn.execute(
        "INSERT INTO task_assignment VALUES ('node-2', 'did:mock:agent-1', 'failed')"
    )
    conn.commit()
    conn.close()

    return svc


class TestObservatoryServiceInit:
    def test_service_instantiates(self, service: ObservatoryService) -> None:
        assert service is not None

    def test_service_stores_db_path(self, tmp_path: Path) -> None:
        db = tmp_path / "check.db"
        svc = ObservatoryService(str(db))
        assert svc._db_path == str(db)


class TestObservatoryServiceSummary:
    def test_summary_returns_dict(self, service: ObservatoryService) -> None:
        result = service.get_summary()
        assert isinstance(result, dict)

    def test_summary_has_required_keys(self, service: ObservatoryService) -> None:
        result = service.get_summary()
        assert "sessions_by_state" in result
        assert "agents_by_type" in result
        assert "tasks_in_progress" in result
        assert "treasury_balance" in result
        assert "active_alerts" in result

    def test_summary_defaults_to_zero_on_empty_db(self, service: ObservatoryService) -> None:
        result = service.get_summary()
        assert result["tasks_in_progress"] == 0
        assert result["treasury_balance"] == 0.0
        assert result["active_alerts"] == 0

    def test_summary_populated(self, populated_service: ObservatoryService) -> None:
        result = populated_service.get_summary()
        assert result["sessions_by_state"]["OPEN"] == 1
        assert result["sessions_by_state"]["CLOSED"] == 1
        assert "producer" in result["agents_by_type"]
        assert result["treasury_balance"] == 110.0


class TestObservatoryServiceLeaderboard:
    def test_leaderboard_empty_db(self, service: ObservatoryService) -> None:
        result = service.get_leaderboard()
        assert result == []

    def test_leaderboard_returns_list(self, populated_service: ObservatoryService) -> None:
        result = populated_service.get_leaderboard()
        assert isinstance(result, list)

    def test_leaderboard_rank_starts_at_one(self, populated_service: ObservatoryService) -> None:
        result = populated_service.get_leaderboard()
        assert len(result) >= 1
        assert result[0]["rank"] == 1

    def test_leaderboard_filter_by_type(self, populated_service: ObservatoryService) -> None:
        result = populated_service.get_leaderboard(agent_type="producer")
        assert all(r["agent_type"] == "producer" for r in result)

    def test_leaderboard_limit(self, populated_service: ObservatoryService) -> None:
        result = populated_service.get_leaderboard(limit=1)
        assert len(result) <= 1


class TestObservatoryServiceTimeseries:
    def test_reputation_timeseries_empty(self, service: ObservatoryService) -> None:
        assert service.get_reputation_timeseries() == []

    def test_reputation_timeseries_populated(self, populated_service: ObservatoryService) -> None:
        result = populated_service.get_reputation_timeseries()
        assert len(result) == 1
        assert result[0]["agent_did"] == "did:mock:agent-1"

    def test_reputation_timeseries_filter_agent(
        self, populated_service: ObservatoryService
    ) -> None:
        result = populated_service.get_reputation_timeseries(agent_did="did:mock:nobody")
        assert result == []

    def test_treasury_timeseries_empty(self, service: ObservatoryService) -> None:
        assert service.get_treasury_timeseries() == []

    def test_treasury_timeseries_populated(self, populated_service: ObservatoryService) -> None:
        result = populated_service.get_treasury_timeseries()
        assert len(result) == 1
        assert result[0]["balance_after"] == 110.0


class TestObservatoryServiceEvents:
    def test_get_events_empty(self, service: ObservatoryService) -> None:
        assert service.get_events() == []

    def test_get_events_populated(self, populated_service: ObservatoryService) -> None:
        result = populated_service.get_events()
        assert len(result) == 1
        assert result[0]["event_type"] == "session.open"

    def test_get_events_filter_type(self, populated_service: ObservatoryService) -> None:
        result = populated_service.get_events(event_type="no.such.event")
        assert result == []

    def test_get_events_since_filters(self, populated_service: ObservatoryService) -> None:
        result = populated_service.get_events(since=999)
        assert result == []


class TestObservatoryServiceSessionsTimeline:
    def test_sessions_timeline_empty(self, service: ObservatoryService) -> None:
        assert service.get_sessions_timeline() == []

    def test_sessions_timeline_populated(self, populated_service: ObservatoryService) -> None:
        result = populated_service.get_sessions_timeline()
        assert len(result) == 2
        assert all("session_id" in r for r in result)


class TestObservatoryServiceHeatmap:
    def test_heatmap_empty_db(self, service: ObservatoryService) -> None:
        result = service.get_execution_heatmap()
        assert result == {"agents": {}, "rows": []}

    def test_heatmap_populated(self, populated_service: ObservatoryService) -> None:
        result = populated_service.get_execution_heatmap()
        assert "did:mock:agent-1" in result["agents"]
        assert len(result["rows"]) >= 1
