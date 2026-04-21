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
"""Unit tests for ExecutionService (RP2-C).

Tests the service layer directly (no HTTP), using a temp SQLite DB.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from oasis.config import PlatformConfig
from oasis.execution.schema import create_execution_tables
from oasis.execution.service import ExecutionService, ExecutionServiceError
from oasis.governance.schema import create_governance_tables, seed_clerks, seed_constitution


@pytest.fixture()
def service(tmp_path: Path) -> ExecutionService:
    """ExecutionService backed by a fresh temp DB with all required tables."""
    db = tmp_path / "exec_service_test.db"
    create_governance_tables(db)
    seed_constitution(db)
    seed_clerks(db)
    create_execution_tables(db)
    return ExecutionService(str(db), PlatformConfig(execution_mode="synthetic"))


class TestExecutionServiceInit:
    def test_service_instantiates(self, service: ExecutionService) -> None:
        assert service is not None

    def test_service_stores_db_path(self, tmp_path: Path) -> None:
        db = tmp_path / "check.db"
        create_governance_tables(db)
        seed_constitution(db)
        seed_clerks(db)
        create_execution_tables(db)
        svc = ExecutionService(str(db))
        assert svc._db_path == str(db)

    def test_service_uses_default_config(self, tmp_path: Path) -> None:
        db = tmp_path / "check2.db"
        create_governance_tables(db)
        seed_constitution(db)
        seed_clerks(db)
        create_execution_tables(db)
        svc = ExecutionService(str(db))
        assert svc._config is not None


class TestExecutionServiceGetTask:
    def test_missing_task_raises_404(self, service: ExecutionService) -> None:
        with pytest.raises(ExecutionServiceError) as exc_info:
            service.get_task("does-not-exist")
        assert exc_info.value.status_code == 404

    def test_missing_task_message(self, service: ExecutionService) -> None:
        with pytest.raises(ExecutionServiceError) as exc_info:
            service.get_task("phantom-task")
        assert "phantom-task" in str(exc_info.value)


class TestExecutionServiceGetSettlement:
    def test_missing_task_raises_404(self, service: ExecutionService) -> None:
        with pytest.raises(ExecutionServiceError) as exc_info:
            service.get_settlement("no-such-task")
        assert exc_info.value.status_code == 404

    def test_existing_task_not_settled(self, tmp_path: Path) -> None:
        """A task that exists but has no settlement row returns settled=False."""
        import sqlite3

        db = tmp_path / "settle.db"
        create_governance_tables(db)
        seed_constitution(db)
        seed_clerks(db)
        create_execution_tables(db)

        task_id = "test-task-001"
        conn = sqlite3.connect(str(db))
        conn.execute("PRAGMA foreign_keys = OFF")
        conn.execute(
            "INSERT INTO task_assignment (task_id, session_id, node_id, agent_did, status) "
            "VALUES (?, 'sess-1', 'node-1', 'did:mock:agent-1', 'assigned')",
            (task_id,),
        )
        conn.commit()
        conn.close()

        svc = ExecutionService(str(db))
        result = svc.get_settlement(task_id)
        assert result["settled"] is False
        assert result["settlement"] is None


class TestExecutionServiceListTasks:
    def test_list_session_tasks_empty(self, service: ExecutionService) -> None:
        result = service.list_session_tasks("nonexistent-session")
        assert result["session_id"] == "nonexistent-session"
        assert result["tasks"] == []

    def test_list_agent_tasks_empty(self, service: ExecutionService) -> None:
        result = service.list_agent_tasks("did:mock:nobody")
        assert result["agent_did"] == "did:mock:nobody"
        assert result["tasks"] == []
