from __future__ import annotations

from fastapi.testclient import TestClient

from oasis.api import app


def _normalize_feed_payload(payload: object) -> list[dict]:
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        items = payload.get("items")
        if isinstance(items, list):
            return items
    return []


def test_batch_observations_matches_single_agent_shapes():
    with TestClient(app) as client:
        signup = client.post(
            "/api/users",
            json={"agent_id": 1, "user_name": "agent-1", "name": "Agent 1", "bio": ""},
        )
        assert signup.status_code == 200, signup.text

        batch = client.post(
            "/api/mitosis/observations/batch",
            json={"agent_ids": ["agent-1"], "limit": 20},
        )
        assert batch.status_code == 200, batch.text
        observation = batch.json()["observations"]["agent-1"]

        single_feed = client.get("/api/feed", params={"agent_id": 1})
        single_tasks = client.get("/api/v1/execution/agents/did:mock:agent-1/tasks")
        single_balance = client.get("/api/v1/adjudication/agents/did:mock:agent-1/balance")
        assert single_feed.status_code == 200, single_feed.text
        assert single_tasks.status_code == 200, single_tasks.text
        assert single_balance.status_code == 200, single_balance.text

        balance_payload = single_balance.json()
        expected_balance = balance_payload["total_balance"]

        assert observation["agent_id"] == "agent-1"
        assert observation["environment"]["type"] == "oasis_social_simulation"
        assert observation["environment"]["social_feed"] == _normalize_feed_payload(single_feed.json())
        assert observation["environment"]["mission_board"] == single_tasks.json()
        assert observation["environment"]["state"]["agent_balance"] == expected_balance
        assert observation["private_context"] == {"balance": expected_balance}


def test_batch_observations_handles_invalid_ids_without_corrupting_valid_ones():
    with TestClient(app) as client:
        signup = client.post(
            "/api/users",
            json={"agent_id": 2, "user_name": "agent-2", "name": "Agent 2", "bio": ""},
        )
        assert signup.status_code == 200, signup.text

        batch = client.post(
            "/api/mitosis/observations/batch",
            json={"agent_ids": ["agent-2", "invalid-agent"], "limit": 5},
        )
        assert batch.status_code == 200, batch.text
        observations = batch.json()["observations"]

        assert "agent-2" in observations
        assert "invalid-agent" in observations
        assert observations["agent-2"]["environment"]["type"] == "oasis_social_simulation"
        assert observations["invalid-agent"]["environment"]["social_feed"] == []
