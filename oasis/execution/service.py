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
"""oasis/execution/service.py
===========================
ExecutionService: business logic extracted from endpoints.py (RP2-C).

Holds all state (db_path, config, dispatcher) as instance attributes instead
of module-level globals so tests can instantiate with a temp DB and the
FastAPI app can hold a singleton created at startup.
"""
from __future__ import annotations

import json
import sqlite3
from typing import Any

from oasis.config import PlatformConfig
from oasis.execution.commitment import commit_to_task
from oasis.execution.router import get_agent_tasks, get_session_tasks
from oasis.execution.runner import ExecutionDispatcher


class ExecutionServiceError(Exception):
    """Raised when service logic cannot fulfil a request."""

    def __init__(self, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.status_code = status_code


class ExecutionService:
    """Domain service for execution-layer operations."""

    def __init__(self, db_path: str, config: PlatformConfig | None = None) -> None:
        self._db_path = db_path
        self._config = config or PlatformConfig()
        self._dispatcher = ExecutionDispatcher(self._config, db_path)

    # ── helpers ───────────────────────────────────────────────────────────────

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path)
        conn.execute("PRAGMA foreign_keys = ON")
        conn.row_factory = sqlite3.Row
        return conn

    # ── public methods ────────────────────────────────────────────────────────

    def get_task(self, task_id: str) -> dict[str, Any]:
        """Return task details + DAG node info."""
        conn = self._connect()
        try:
            task = conn.execute(
                "SELECT * FROM task_assignment WHERE task_id = ?", (task_id,)
            ).fetchone()
            if task is None:
                raise ExecutionServiceError(f"Task not found: {task_id}", 404)

            node = conn.execute(
                "SELECT label, service_id, input_schema, output_schema, "
                "token_budget, timeout_ms FROM dag_node WHERE node_id = ?",
                (task["node_id"],),
            ).fetchone()

            node_info = None
            if node is not None:
                node_info = {
                    "label": node["label"],
                    "service_id": node["service_id"],
                    "input_schema": json.loads(node["input_schema"]) if node["input_schema"] else None,
                    "output_schema": json.loads(node["output_schema"]) if node["output_schema"] else None,
                    "token_budget": node["token_budget"],
                    "timeout_ms": node["timeout_ms"],
                }

            return {
                "task_id": task["task_id"],
                "session_id": task["session_id"],
                "node_id": task["node_id"],
                "agent_did": task["agent_did"],
                "status": task["status"],
                "created_at": task["created_at"],
                "node": node_info,
            }
        finally:
            conn.close()

    def commit_task(self, task_id: str, agent_did: str) -> dict[str, Any]:
        """Commit an agent to a task (lock stake)."""
        try:
            return commit_to_task(task_id, agent_did, self._db_path)
        except ValueError as exc:
            raise ExecutionServiceError(str(exc), 400)

    def submit_output(self, task_id: str, output_data: str, agent_did: str) -> dict[str, Any]:
        """Submit task output (LLM mode)."""
        try:
            return self._dispatcher.receive_output(task_id, output_data, agent_did)
        except ValueError as exc:
            raise ExecutionServiceError(str(exc), 400)

    def get_task_status(self, task_id: str) -> dict[str, Any]:
        """Return task status including output and validation state."""
        try:
            status = self._dispatcher.get_task_status(task_id)
            return {
                "task_id": status.task_id,
                "status": status.status,
                "agent_did": status.agent_did,
                "has_output": status.has_output,
                "has_validation": status.has_validation,
            }
        except ValueError as exc:
            raise ExecutionServiceError(str(exc), 404)

    def get_settlement(self, task_id: str) -> dict[str, Any]:
        """Return settlement result for a completed task."""
        conn = self._connect()
        try:
            task = conn.execute(
                "SELECT task_id FROM task_assignment WHERE task_id = ?", (task_id,)
            ).fetchone()
            if task is None:
                raise ExecutionServiceError(f"Task not found: {task_id}", 404)

            settlement = conn.execute(
                "SELECT * FROM settlement WHERE task_id = ?", (task_id,)
            ).fetchone()
            if settlement is None:
                return {"task_id": task_id, "settled": False, "settlement": None}

            return {
                "task_id": task_id,
                "settled": True,
                "settlement": {
                    "settlement_id": settlement["settlement_id"],
                    "agent_did": settlement["agent_did"],
                    "base_reward": settlement["base_reward"],
                    "reputation_multiplier": settlement["reputation_multiplier"],
                    "final_reward": settlement["final_reward"],
                    "protocol_fee": settlement["protocol_fee"],
                    "insurance_fee": settlement["insurance_fee"],
                    "treasury_subsidy": settlement["treasury_subsidy"],
                    "settled_at": settlement["settled_at"],
                },
            }
        finally:
            conn.close()

    def list_session_tasks(self, session_id: str) -> dict[str, Any]:
        tasks = get_session_tasks(session_id, self._db_path)
        return {"session_id": session_id, "tasks": tasks}

    def list_agent_tasks(self, agent_did: str) -> dict[str, Any]:
        tasks = get_agent_tasks(agent_did, self._db_path)
        return {"agent_did": agent_did, "tasks": tasks}
