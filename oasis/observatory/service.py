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
"""oasis/observatory/service.py
================================
ObservatoryService: business logic extracted from endpoints.py (RP2-C).

Encapsulates the SQLite db_path and all query logic so endpoints.py becomes
thin HTTP delegates and tests can instantiate with a temp DB.
"""
from __future__ import annotations

import json
import sqlite3
from typing import Any

from oasis.observatory.schema import create_observatory_tables


class ObservatoryService:
    """Read-side query service for simulation observability data."""

    def __init__(self, db_path: str) -> None:
        self._db_path = db_path
        create_observatory_tables(db_path)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path)
        conn.execute("PRAGMA foreign_keys = ON")
        conn.row_factory = sqlite3.Row
        return conn

    # ── Summary ───────────────────────────────────────────────────────────────

    def get_summary(self) -> dict[str, Any]:
        conn = self._connect()
        try:
            sessions_by_state: dict[str, int] = {}
            try:
                rows = conn.execute(
                    "SELECT state, COUNT(*) as cnt FROM legislative_session GROUP BY state"
                ).fetchall()
                sessions_by_state = {r["state"]: r["cnt"] for r in rows}
            except sqlite3.OperationalError:
                pass

            agents_by_type: dict[str, int] = {}
            try:
                rows = conn.execute(
                    "SELECT agent_type, COUNT(*) as cnt FROM agent_registry GROUP BY agent_type"
                ).fetchall()
                agents_by_type = {r["agent_type"]: r["cnt"] for r in rows}
            except sqlite3.OperationalError:
                pass

            tasks_in_progress = 0
            try:
                row = conn.execute(
                    "SELECT COUNT(*) as cnt FROM task_assignment "
                    "WHERE status NOT IN ('settled', 'failed')"
                ).fetchone()
                tasks_in_progress = row["cnt"] if row else 0
            except sqlite3.OperationalError:
                pass

            treasury_balance = 0.0
            try:
                row = conn.execute(
                    "SELECT balance_after FROM treasury ORDER BY entry_id DESC LIMIT 1"
                ).fetchone()
                treasury_balance = row["balance_after"] if row else 0.0
            except sqlite3.OperationalError:
                pass

            active_alerts = 0
            try:
                row = conn.execute("SELECT COUNT(*) as cnt FROM guardian_alert").fetchone()
                active_alerts = row["cnt"] if row else 0
            except sqlite3.OperationalError:
                pass

            return {
                "sessions_by_state": sessions_by_state,
                "agents_by_type": agents_by_type,
                "tasks_in_progress": tasks_in_progress,
                "treasury_balance": treasury_balance,
                "active_alerts": active_alerts,
            }
        finally:
            conn.close()

    # ── Leaderboard ───────────────────────────────────────────────────────────

    def get_leaderboard(
        self,
        sort_by: str = "reputation_score",
        limit: int = 20,
        agent_type: str | None = None,
    ) -> list[dict[str, Any]]:
        allowed_sorts = {
            "reputation_score": "ar.reputation_score",
            "total_balance": "COALESCE(ab.total_balance, 0)",
            "available_balance": "COALESCE(ab.available_balance, 0)",
        }
        order_col = allowed_sorts.get(sort_by, "ar.reputation_score")
        where_clause = "WHERE ar.agent_type = ? " if agent_type is not None else ""
        params: list[Any] = ([agent_type, limit] if agent_type is not None else [limit])

        query = (
            "SELECT ar.agent_did, ar.display_name, ar.agent_type, "
            "ar.reputation_score, "
            "COALESCE(ab.total_balance, 0) as total_balance, "
            "COALESCE(ab.available_balance, 0) as available_balance, "
            "COALESCE(ab.locked_stake, 0) as locked_stake "
            "FROM agent_registry ar "
            "LEFT JOIN agent_balance ab ON ar.agent_did = ab.agent_did "
            f"{where_clause}"
            f"ORDER BY {order_col} DESC "
            "LIMIT ?"
        )
        conn = self._connect()
        try:
            rows = conn.execute(query, params).fetchall()
            return [
                {
                    "rank": i + 1,
                    "agent_did": r["agent_did"],
                    "display_name": r["display_name"],
                    "agent_type": r["agent_type"],
                    "reputation_score": r["reputation_score"],
                    "total_balance": r["total_balance"],
                    "available_balance": r["available_balance"],
                    "locked_stake": r["locked_stake"],
                }
                for i, r in enumerate(rows)
            ]
        except sqlite3.OperationalError:
            return []
        finally:
            conn.close()

    # ── Timeseries ────────────────────────────────────────────────────────────

    def get_reputation_timeseries(
        self,
        agent_did: str | None = None,
        since: str | None = None,
        until: str | None = None,
    ) -> list[dict[str, Any]]:
        query = "SELECT * FROM reputation_ledger WHERE 1=1"
        params: list[str] = []
        if agent_did is not None:
            query += " AND agent_did = ?"
            params.append(agent_did)
        if since is not None:
            query += " AND created_at >= ?"
            params.append(since)
        if until is not None:
            query += " AND created_at <= ?"
            params.append(until)
        query += " ORDER BY created_at ASC"

        conn = self._connect()
        try:
            rows = conn.execute(query, params).fetchall()
            return [
                {
                    "entry_id": r["entry_id"],
                    "agent_did": r["agent_did"],
                    "old_score": r["old_score"],
                    "new_score": r["new_score"],
                    "performance_score": r["performance_score"],
                    "reason": r["reason"],
                    "created_at": r["created_at"],
                }
                for r in rows
            ]
        except sqlite3.OperationalError:
            return []
        finally:
            conn.close()

    def get_treasury_timeseries(self) -> list[dict[str, Any]]:
        conn = self._connect()
        try:
            rows = conn.execute(
                "SELECT entry_id, entry_type, amount, balance_after, created_at "
                "FROM treasury ORDER BY entry_id ASC"
            ).fetchall()
            return [
                {
                    "entry_id": r["entry_id"],
                    "entry_type": r["entry_type"],
                    "amount": r["amount"],
                    "balance_after": r["balance_after"],
                    "created_at": r["created_at"],
                }
                for r in rows
            ]
        except sqlite3.OperationalError:
            return []
        finally:
            conn.close()

    # ── Events ────────────────────────────────────────────────────────────────

    def get_events(
        self,
        event_type: str | None = None,
        session_id: str | None = None,
        agent_did: str | None = None,
        since: int = 0,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        query = "SELECT * FROM event_log WHERE sequence_number > ?"
        params: list[Any] = [since]
        if event_type is not None:
            query += " AND event_type = ?"
            params.append(event_type)
        if session_id is not None:
            query += " AND session_id = ?"
            params.append(session_id)
        if agent_did is not None:
            query += " AND agent_did = ?"
            params.append(agent_did)
        query += " ORDER BY sequence_number ASC LIMIT ? OFFSET ?"
        params.extend([limit, offset])

        conn = self._connect()
        try:
            rows = conn.execute(query, params).fetchall()
            return [
                {
                    "event_id": r["event_id"],
                    "event_type": r["event_type"],
                    "timestamp": r["timestamp"],
                    "session_id": r["session_id"],
                    "agent_did": r["agent_did"],
                    "payload": json.loads(r["payload"]) if r["payload"] else {},
                    "sequence_number": r["sequence_number"],
                }
                for r in rows
            ]
        finally:
            conn.close()

    # ── Session timeline ──────────────────────────────────────────────────────

    def get_sessions_timeline(self) -> list[dict[str, Any]]:
        conn = self._connect()
        try:
            rows = conn.execute(
                "SELECT session_id, state, created_at FROM legislative_session "
                "ORDER BY created_at ASC"
            ).fetchall()
            return [
                {"session_id": r["session_id"], "state": r["state"], "created_at": r["created_at"]}
                for r in rows
            ]
        except sqlite3.OperationalError:
            return []
        finally:
            conn.close()

    # ── Execution heatmap ─────────────────────────────────────────────────────

    def get_execution_heatmap(self) -> dict[str, Any]:
        conn = self._connect()
        try:
            rows = conn.execute(
                "SELECT agent_did, node_id, status FROM task_assignment "
                "ORDER BY agent_did, node_id"
            ).fetchall()
            agents: dict[str, dict[str, str]] = {}
            for r in rows:
                agent = r["agent_did"]
                if agent not in agents:
                    agents[agent] = {}
                agents[agent][r["node_id"]] = r["status"]
            return {
                "agents": agents,
                "rows": [{"agent_did": a, "tasks": t} for a, t in agents.items()],
            }
        except sqlite3.OperationalError:
            return {"agents": {}, "rows": []}
        finally:
            conn.close()
