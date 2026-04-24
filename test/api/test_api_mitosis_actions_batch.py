from __future__ import annotations

from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from oasis.api import ActionType, app


def test_batch_actions_matches_idle_and_social_behavior():
    with TestClient(app) as client:
        for agent_id in (1, 2):
            signup = client.post(
                "/api/users",
                json={
                    "agent_id": agent_id,
                    "user_name": f"agent-{agent_id}",
                    "name": f"Agent {agent_id}",
                    "bio": "",
                },
            )
            assert signup.status_code == 200, signup.text

        with patch("oasis.api._dispatch", new_callable=AsyncMock) as mock_dispatch:
            batch = client.post(
                "/api/mitosis/actions/batch",
                json={
                    "actions": {
                        "agent-1": {
                            "action": {"type": "idle"},
                            "social_action": "hello from batch",
                        }
                    }
                },
            )
            assert batch.status_code == 200, batch.text
            result = batch.json()["results"]["agent-1"]
            assert result["success"] is True
            assert result["action_type"] == "idle"
            mock_dispatch.assert_awaited_once_with(
                ActionType.CREATE_POST,
                1,
                "hello from batch",
            )


def test_batch_actions_handles_multiple_agents_deterministically():
    with TestClient(app) as client:
        for agent_id in (2, 3):
            signup = client.post(
                "/api/users",
                json={
                    "agent_id": agent_id,
                    "user_name": f"agent-{agent_id}",
                    "name": f"Agent {agent_id}",
                    "bio": "",
                },
            )
            assert signup.status_code == 200, signup.text

        batch = client.post(
            "/api/mitosis/actions/batch",
            json={
                "actions": {
                    "agent-3": {"action": {"type": "idle"}},
                    "agent-2": {"action": {"type": "idle"}},
                }
            },
        )
        assert batch.status_code == 200, batch.text
        results = batch.json()["results"]
        assert list(results.keys()) == ["agent-2", "agent-3"]
        assert results["agent-2"]["success"] is True
        assert results["agent-3"]["success"] is True
