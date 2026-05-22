"""Tests for state/stage fields in task responses and the transitions endpoint.

Bundle 4 — Execution State Machine + Pipeline Stage
Coverage: T1 (state/stage in GET /tasks/{task_id}), T2 (404),
          T3 (transitions ordered), plus edge cases.
"""

from __future__ import annotations

import sqlite3

import pytest
from fastapi.testclient import TestClient

from oasis.api import app
from oasis.config import PlatformConfig
from oasis.execution import endpoints as exec_ep
from oasis.execution.router import route_tasks
from oasis.execution.schema import create_execution_tables
from oasis.governance.schema import (
    create_governance_tables,
    seed_clerks,
    seed_constitution,
)

from .conftest import EXEC_PRODUCERS, drive_to_deployed


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def exec_db(tmp_path):
    """Set up a full DB with governance + execution tables, wired into endpoints."""
    db = tmp_path / "exec_state_stage_test.db"
    create_governance_tables(db)
    seed_constitution(db)
    seed_clerks(db)
    create_execution_tables(db)

    from oasis.governance import endpoints as gov_ep

    gov_ep.init_governance_db(str(db))

    config = PlatformConfig(execution_mode="llm")
    exec_ep.init_execution_db(str(db), config)
    return db


@pytest.fixture()
def api_producers(exec_db):
    conn = sqlite3.connect(str(exec_db))
    conn.execute("PRAGMA foreign_keys = ON")
    for p in EXEC_PRODUCERS:
        conn.execute(
            "INSERT OR IGNORE INTO agent_registry "
            "(agent_did, agent_type, display_name, human_principal, reputation_score, public_key) "
            "VALUES (?, 'producer', ?, 'human@example.com', ?, ?)",
            (p["agent_did"], p["display_name"], p["reputation_score"], p["public_key"]),
        )
    conn.commit()
    conn.close()
    return list(EXEC_PRODUCERS)


@pytest.fixture()
def client(exec_db) -> TestClient:
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture()
def routed_tasks(exec_db, api_producers):
    info = drive_to_deployed(exec_db, api_producers)
    tasks = route_tasks(info["session_id"], exec_db)
    return tasks, info


# ---------------------------------------------------------------------------
# T1 — Happy path: state and stage appear in GET /tasks/{task_id}
# ---------------------------------------------------------------------------


class TestStateAndStageInTaskResponse:
    def test_get_task_includes_state_and_stage(self, client, routed_tasks, exec_db):
        """Task with state='EXECUTING' and stage='INVOKE' returns both fields."""
        tasks, _ = routed_tasks
        task = tasks[0]
        conn = sqlite3.connect(str(exec_db))
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute(
            "UPDATE task_assignment SET state = ?, stage = ? WHERE task_id = ?",
            ("EXECUTING", "INVOKE", task["task_id"]),
        )
        conn.commit()
        conn.close()

        resp = client.get(f"/api/execution/tasks/{task['task_id']}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["state"] == "EXECUTING"
        assert data["stage"] == "INVOKE"

    def test_v1_get_task_includes_state_and_stage(self, client, routed_tasks, exec_db):
        """V1 prefix also returns state and stage."""
        tasks, _ = routed_tasks
        task = tasks[0]
        conn = sqlite3.connect(str(exec_db))
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute(
            "UPDATE task_assignment SET state = ?, stage = ? WHERE task_id = ?",
            ("EXECUTING", "INVOKE", task["task_id"]),
        )
        conn.commit()
        conn.close()

        resp = client.get(f"/api/v1/execution/tasks/{task['task_id']}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["state"] == "EXECUTING"
        assert data["stage"] == "INVOKE"

    def test_get_task_preserves_legacy_status(self, client, routed_tasks, exec_db):
        """Legacy status field remains alongside state for backward compatibility."""
        tasks, _ = routed_tasks
        task = tasks[0]
        conn = sqlite3.connect(str(exec_db))
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute(
            "UPDATE task_assignment SET state = ?, stage = ?, status = ? WHERE task_id = ?",
            ("EXECUTING", "INVOKE", "committed", task["task_id"]),
        )
        conn.commit()
        conn.close()

        resp = client.get(f"/api/execution/tasks/{task['task_id']}")
        assert resp.status_code == 200
        data = resp.json()
        assert "status" in data
        assert data["status"] == "committed"
        assert "state" in data
        assert data["state"] == "EXECUTING"
        assert "stage" in data
        assert data["stage"] == "INVOKE"


# ---------------------------------------------------------------------------
# T2 — Error case: unknown task_id returns 404
# ---------------------------------------------------------------------------


class TestGetTask404:
    def test_get_task_unknown_returns_404(self, client):
        resp = client.get("/api/execution/tasks/nonexistent-task-id")
        assert resp.status_code == 404

    def test_v1_get_task_unknown_returns_404(self, client):
        resp = client.get("/api/v1/execution/tasks/nonexistent-task-id")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# T3 — Edge case: transitions endpoint returns ordered audit rows
# ---------------------------------------------------------------------------


class TestTaskTransitions:
    def test_get_task_transitions_ordered(self, client, routed_tasks, exec_db):
        """Rows ordered by transitioned_at ascending."""
        tasks, _ = routed_tasks
        task_id = tasks[0]["task_id"]

        conn = sqlite3.connect(str(exec_db))
        conn.execute("PRAGMA foreign_keys = ON")
        conn.executemany(
            "INSERT INTO task_state_transition "
            "(task_id, from_state, to_state, from_stage, to_stage, transitioned_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            [
                (
                    task_id,
                    "WAITING",
                    "ELIGIBLE",
                    "ORCHESTRATE",
                    "INVOKE",
                    "2024-01-01 10:00:00",
                ),
                (
                    task_id,
                    "ELIGIBLE",
                    "EXECUTING",
                    "INVOKE",
                    "COMMIT",
                    "2024-01-01 10:05:00",
                ),
                (
                    task_id,
                    "EXECUTING",
                    "COMPLETED",
                    "COMMIT",
                    "RECORD",
                    "2024-01-01 10:10:00",
                ),
            ],
        )
        conn.commit()
        conn.close()

        resp = client.get(f"/api/execution/tasks/{task_id}/transitions")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 3
        assert data[0]["to_state"] == "ELIGIBLE"
        assert data[1]["to_state"] == "EXECUTING"
        assert data[2]["to_state"] == "COMPLETED"

    def test_v1_get_task_transitions_ordered(self, client, routed_tasks, exec_db):
        """V1 prefix also returns ordered transitions."""
        tasks, _ = routed_tasks
        task_id = tasks[0]["task_id"]

        conn = sqlite3.connect(str(exec_db))
        conn.execute("PRAGMA foreign_keys = ON")
        conn.executemany(
            "INSERT INTO task_state_transition "
            "(task_id, from_state, to_state, from_stage, to_stage, transitioned_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            [
                (
                    task_id,
                    "WAITING",
                    "ELIGIBLE",
                    "ORCHESTRATE",
                    "INVOKE",
                    "2024-01-01 10:00:00",
                ),
                (
                    task_id,
                    "ELIGIBLE",
                    "EXECUTING",
                    "INVOKE",
                    "COMMIT",
                    "2024-01-01 10:05:00",
                ),
                (
                    task_id,
                    "EXECUTING",
                    "COMPLETED",
                    "COMMIT",
                    "RECORD",
                    "2024-01-01 10:10:00",
                ),
            ],
        )
        conn.commit()
        conn.close()

        resp = client.get(f"/api/v1/execution/tasks/{task_id}/transitions")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 3
        assert data[0]["to_state"] == "ELIGIBLE"
        assert data[1]["to_state"] == "EXECUTING"
        assert data[2]["to_state"] == "COMPLETED"

    def test_get_task_transitions_unknown_returns_404(self, client):
        """Unknown task_id on transitions endpoint returns 404 with task detail."""
        resp = client.get("/api/execution/tasks/unknown-task-id/transitions")
        assert resp.status_code == 404
        # Distinguish from the generic FastAPI "Not Found" returned when the
        # route itself is missing — once implemented the detail should mention
        # the task id.
        detail = resp.json().get("detail", "")
        assert "unknown-task-id" in detail

    def test_v1_get_task_transitions_unknown_returns_404(self, client):
        resp = client.get("/api/v1/execution/tasks/unknown-task-id/transitions")
        assert resp.status_code == 404
        detail = resp.json().get("detail", "")
        assert "unknown-task-id" in detail
