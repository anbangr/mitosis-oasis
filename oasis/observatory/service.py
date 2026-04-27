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
import logging
import sqlite3
from typing import Any

from oasis.observatory.schema import create_observatory_tables

logger = logging.getLogger(__name__)


class ObservatoryService:
    """Read-side query service for simulation observability data."""

    def __init__(
        self,
        db_path: str,
        *,
        governance_db: str | None = None,
        execution_db: str | None = None,
        adjudication_db: str | None = None,
    ) -> None:
        self._db_path = db_path
        self._governance_db = governance_db
        self._execution_db = execution_db
        self._adjudication_db = adjudication_db
        create_observatory_tables(db_path)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path)
        conn.execute("PRAGMA foreign_keys = ON")
        conn.row_factory = sqlite3.Row
        return conn

    def _connect_for_metrics(self) -> sqlite3.Connection:
        """Open observatory DB and ATTACH branch DBs for cross-branch metric queries."""
        conn = sqlite3.connect(self._db_path)
        conn.execute("PRAGMA foreign_keys = ON")
        conn.row_factory = sqlite3.Row
        if self._governance_db:
            conn.execute("ATTACH DATABASE ? AS gov", (self._governance_db,))
        if self._execution_db:
            conn.execute("ATTACH DATABASE ? AS exec_db", (self._execution_db,))
        if self._adjudication_db:
            conn.execute("ATTACH DATABASE ? AS adj", (self._adjudication_db,))
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

    # ── Governance experiment metrics (Gap 6) ─────────────────────────────────

    def get_governance_metrics(self) -> dict[str, Any]:
        """Compute AgentCity experiment metrics from available cross-branch data.

        Metrics returned:
        - pcr  (Project Completion Rate): DEPLOYED sessions / total sessions
        - psr  (Pool Sustainability Rate): active producers / total producers
        - cau  (Capability-Adjusted Utilization): T3+T5 completed tasks / all completed
        - si   (Specialization Index): 1 - normalised HHI of completed tasks by tier
        - cdr  (Coordination Detection Rate): ratio of coordination-flagged events
        - opa  (Override Panel Activation count): guardian alerts raised
        - ecp  (Endogenous Compliance Premium): mean reputation delta (new - old)
        - session_count: total sessions in all states
        - active_agent_count: number of currently active producer agents
        """
        conn = self._connect_for_metrics()
        # Table-name prefixes: use schema-qualified names when the branch DB is
        # ATTACHed, otherwise fall back to unqualified names (works in tests where
        # all tables are seeded directly into the observatory DB).
        gov = "gov." if self._governance_db else ""
        exc = "exec_db." if self._execution_db else ""
        adj = "adj." if self._adjudication_db else ""

        metrics: dict[str, Any] = {}
        try:
            # PCR — Project Completion Rate
            try:
                total_row = conn.execute(
                    f"SELECT COUNT(*) as cnt FROM {gov}legislative_session"
                ).fetchone()
                deployed_row = conn.execute(
                    f"SELECT COUNT(*) as cnt FROM {gov}legislative_session WHERE state = 'DEPLOYED'"
                ).fetchone()
                total_sessions = total_row["cnt"] if total_row else 0
                deployed = deployed_row["cnt"] if deployed_row else 0
                metrics["pcr"] = round(deployed / total_sessions, 4) if total_sessions > 0 else 0.0
                metrics["session_count"] = total_sessions
            except sqlite3.OperationalError as err:
                logger.warning("PCR metric unavailable — governance tables missing or not yet created: %s", err)
                metrics["pcr"] = 0.0
                metrics["session_count"] = 0

            # PSR — Pool Sustainability Rate
            try:
                total_prod = conn.execute(
                    f"SELECT COUNT(*) as cnt FROM {gov}agent_registry WHERE agent_type = 'producer'"
                ).fetchone()
                active_prod = conn.execute(
                    f"SELECT COUNT(*) as cnt FROM {gov}agent_registry "
                    f"WHERE agent_type = 'producer' AND active = 1"
                ).fetchone()
                total_p = total_prod["cnt"] if total_prod else 0
                active_p = active_prod["cnt"] if active_prod else 0
                metrics["psr"] = round(active_p / total_p, 4) if total_p > 0 else 1.0
                metrics["active_agent_count"] = active_p
            except sqlite3.OperationalError as err:
                logger.warning("PSR metric unavailable — governance tables missing or not yet created: %s", err)
                metrics["psr"] = 1.0
                metrics["active_agent_count"] = 0

            # CAU — Capability-Adjusted Utilization (T3+T5 completed / all completed)
            # Cross-DB join: execution task_assignment × governance agent_registry
            try:
                completed_by_tier = conn.execute(
                    f"SELECT ar.capability_tier, COUNT(*) as cnt "
                    f"FROM {exc}task_assignment ta "
                    f"JOIN {gov}agent_registry ar ON ta.agent_did = ar.agent_did "
                    f"WHERE ta.status IN ('completed', 'settled') "
                    f"GROUP BY ar.capability_tier"
                ).fetchall()
                tier_counts: dict[str, int] = {r["capability_tier"]: r["cnt"] for r in completed_by_tier}
                total_completed = sum(tier_counts.values())
                high_tier = tier_counts.get("t3", 0) + tier_counts.get("t5", 0)
                metrics["cau"] = round(high_tier / total_completed, 4) if total_completed > 0 else 0.0

                # SI — Specialization Index (1 - normalised HHI)
                if total_completed > 0:
                    hhi = sum((c / total_completed) ** 2 for c in tier_counts.values())
                    n = len(tier_counts)
                    hhi_normalised = (hhi - 1 / n) / (1 - 1 / n) if n > 1 else 1.0
                    metrics["si"] = round(max(0.0, min(1.0, 1.0 - hhi_normalised)), 4)
                else:
                    metrics["si"] = 0.0
            except sqlite3.OperationalError as err:
                logger.warning("CAU/SI metrics unavailable — execution or governance tables missing: %s", err)
                metrics["cau"] = 0.0
                metrics["si"] = 0.0

            # CDR — Coordination Detection Rate (coordination events / total vote events)
            # event_log lives in the observatory DB — no schema prefix needed
            try:
                coord_events = conn.execute(
                    "SELECT COUNT(*) as cnt FROM event_log WHERE event_type = 'COORDINATION_FLAGGED'"
                ).fetchone()
                vote_events = conn.execute(
                    "SELECT COUNT(*) as cnt FROM event_log WHERE event_type = 'VOTE_CAST'"
                ).fetchone()
                coord_cnt = coord_events["cnt"] if coord_events else 0
                vote_cnt = vote_events["cnt"] if vote_events else 0
                metrics["cdr"] = round(coord_cnt / vote_cnt, 4) if vote_cnt > 0 else 0.0
            except sqlite3.OperationalError as err:
                logger.warning("CDR metric unavailable — event_log table missing: %s", err)
                metrics["cdr"] = 0.0

            # OPA — Override Panel Activation count (guardian alerts raised)
            try:
                opa_row = conn.execute(
                    f"SELECT COUNT(*) as cnt FROM {adj}guardian_alert"
                ).fetchone()
                metrics["opa"] = opa_row["cnt"] if opa_row else 0
            except sqlite3.OperationalError as err:
                logger.warning("OPA metric unavailable — adjudication tables missing: %s", err)
                metrics["opa"] = 0

            # ECP — Endogenous Compliance Premium (mean reputation improvement)
            # reputation_ledger is defined in the governance schema; query gov. prefix.
            try:
                rep_row = conn.execute(
                    f"SELECT AVG(new_score - old_score) as mean_delta FROM {gov}reputation_ledger"
                ).fetchone()
                delta = rep_row["mean_delta"] if rep_row and rep_row["mean_delta"] is not None else 0.0
                metrics["ecp"] = round(float(delta), 4)
            except sqlite3.OperationalError as err:
                logger.warning("ECP metric unavailable — adjudication tables missing: %s", err)
                metrics["ecp"] = 0.0

        finally:
            conn.close()
        return metrics
