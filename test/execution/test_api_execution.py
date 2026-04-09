"""Tests for execution HTTP endpoints."""
from __future__ import annotations

import json
import sqlite3

import pytest
from fastapi.testclient import TestClient

from oasis.api import app
from oasis.config import PlatformConfig
from oasis.execution import endpoints as exec_ep
from oasis.execution.commitment import commit_to_task
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
    db = tmp_path / "exec_api_test.db"
    create_governance_tables(db)
    seed_constitution(db)
    seed_clerks(db)
    create_execution_tables(db)

    # Also init governance endpoints module
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
            "(agent_did, agent_type, display_name, human_principal, reputation_score) "
            "VALUES (?, 'producer', ?, 'human@example.com', ?)",
            (p["agent_did"], p["display_name"], p["reputation_score"]),
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
# Tests
# ---------------------------------------------------------------------------

class TestExecutionAPI:
    def test_get_task_details(self, client, routed_tasks):
        """GET /api/execution/tasks/{task_id} returns task details."""
        tasks, _ = routed_tasks
        task = tasks[0]
        resp = client.get(f"/api/execution/tasks/{task['task_id']}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["task_id"] == task["task_id"]
        assert data["agent_did"] == task["agent_did"]
        assert data["status"] == "pending"

    def test_commit_to_task(self, client, routed_tasks):
        """POST /api/execution/tasks/{task_id}/commit locks stake."""
        tasks, _ = routed_tasks
        task = tasks[0]
        resp = client.post(
            f"/api/execution/tasks/{task['task_id']}/commit",
            json={"agent_did": task["agent_did"]},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "committed"

    def test_submit_output_requires_executing(self, client, routed_tasks):
        """POST /api/execution/tasks/{task_id}/output rejects non-executing tasks."""
        tasks, _ = routed_tasks
        task = tasks[0]
        # Task is pending, not executing
        resp = client.post(
            f"/api/execution/tasks/{task['task_id']}/output",
            json={
                "agent_did": task["agent_did"],
                "output_data": json.dumps({"result": "test"}),
            },
        )
        assert resp.status_code == 400

    def test_get_task_status(self, client, routed_tasks):
        """GET /api/execution/tasks/{task_id}/status returns status info."""
        tasks, _ = routed_tasks
        task = tasks[0]
        resp = client.get(f"/api/execution/tasks/{task['task_id']}/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "pending"
        assert data["has_output"] is False

    def test_get_settlement_no_settlement(self, client, routed_tasks):
        """GET /api/execution/tasks/{task_id}/settlement returns settled=False."""
        tasks, _ = routed_tasks
        task = tasks[0]
        resp = client.get(f"/api/execution/tasks/{task['task_id']}/settlement")
        assert resp.status_code == 200
        data = resp.json()
        assert data["settled"] is False

    def test_list_session_tasks(self, client, routed_tasks):
        """GET /api/execution/sessions/{session_id}/tasks lists tasks."""
        tasks, info = routed_tasks
        resp = client.get(
            f"/api/execution/sessions/{info['session_id']}/tasks"
        )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["tasks"]) == len(tasks)

    def test_404_for_unknown_task(self, client, routed_tasks):
        """Unknown task_id returns 404."""
        resp = client.get("/api/execution/tasks/nonexistent-task-id")
        assert resp.status_code == 404
