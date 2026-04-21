import sqlite3
import pytest
from fastapi.testclient import TestClient
from fastapi import FastAPI
import tempfile
import os

from oasis.observatory.endpoints import router, init_observatory_db

app = FastAPI()
app.include_router(router)
client = TestClient(app)

@pytest.fixture
def db_path():
    fd, path = tempfile.mkstemp(suffix=".sqlite")
    os.close(fd)
    
    # Init DB and create schemas
    init_observatory_db(path)
    conn = sqlite3.connect(path)
    
    # Create missing tables for summary, leaderboard, timeseries, heatmap
    conn.executescript("""
        CREATE TABLE legislative_session (session_id TEXT, state TEXT, created_at TEXT);
        CREATE TABLE agent_registry (agent_did TEXT, display_name TEXT, agent_type TEXT, reputation_score REAL);
        CREATE TABLE agent_balance (agent_did TEXT, total_balance REAL, available_balance REAL, locked_stake REAL);
        CREATE TABLE task_assignment (node_id TEXT, agent_did TEXT, status TEXT);
        CREATE TABLE treasury (entry_id INTEGER PRIMARY KEY, entry_type TEXT, amount REAL, balance_after REAL, created_at TEXT);
        CREATE TABLE guardian_alert (alert_id TEXT);
        CREATE TABLE reputation_ledger (entry_id INTEGER PRIMARY KEY, agent_did TEXT, old_score REAL, new_score REAL, performance_score REAL, reason TEXT, created_at TEXT);
    """)
    
    # Seed data
    conn.executescript("""
        INSERT INTO legislative_session VALUES ('sess1', 'active', '2023-01-01T00:00:00Z');
        INSERT INTO legislative_session VALUES ('sess2', 'completed', '2023-01-02T00:00:00Z');
        
        INSERT INTO agent_registry VALUES ('did:agent:1', 'Agent 1', 'voter', 100.0);
        INSERT INTO agent_registry VALUES ('did:agent:2', 'Agent 2', 'proposer', 80.0);
        
        INSERT INTO agent_balance VALUES ('did:agent:1', 1000.0, 900.0, 100.0);
        
        INSERT INTO task_assignment VALUES ('task1', 'did:agent:1', 'in_progress');
        INSERT INTO task_assignment VALUES ('task2', 'did:agent:2', 'settled');
        
        INSERT INTO treasury (entry_type, amount, balance_after, created_at) VALUES ('deposit', 500.0, 500.0, '2023-01-01T00:00:00Z');
        INSERT INTO treasury (entry_type, amount, balance_after, created_at) VALUES ('withdrawal', 100.0, 400.0, '2023-01-02T00:00:00Z');
        
        INSERT INTO guardian_alert VALUES ('alert1');
        
        INSERT INTO reputation_ledger (agent_did, old_score, new_score, performance_score, reason, created_at) VALUES ('did:agent:1', 90.0, 100.0, 1.0, 'Good', '2023-01-01T00:00:00Z');
        
        INSERT INTO event_log (event_id, event_type, timestamp, session_id, agent_did, payload, sequence_number) VALUES ('ev1', 'heartbeat', 1.0, 'sess1', 'did:agent:1', '{"key": "value"}', 1);
        INSERT INTO event_log (event_id, event_type, timestamp, session_id, agent_did, payload, sequence_number) VALUES ('ev2', 'vote', 2.0, 'sess1', 'did:agent:2', '{}', 2);
    """)
    conn.commit()
    conn.close()
    
    yield path
    
    os.remove(path)


def test_get_summary(db_path):
    response = client.get("/api/observatory/summary")
    assert response.status_code == 200
    data = response.json()
    assert data["sessions_by_state"]["active"] == 1
    assert data["sessions_by_state"]["completed"] == 1
    assert data["agents_by_type"]["voter"] == 1
    assert data["tasks_in_progress"] == 1
    assert data["treasury_balance"] == 400.0
    assert data["active_alerts"] == 1


def test_get_leaderboard(db_path):
    response = client.get("/api/observatory/agents/leaderboard?sort_by=reputation_score&limit=10")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 2
    assert data[0]["agent_did"] == "did:agent:1"
    assert data[0]["reputation_score"] == 100.0
    assert data[0]["total_balance"] == 1000.0
    assert data[1]["agent_did"] == "did:agent:2"
    assert data[1]["total_balance"] == 0.0


def test_get_reputation_timeseries(db_path):
    response = client.get("/api/observatory/reputation/timeseries")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["agent_did"] == "did:agent:1"
    assert data[0]["new_score"] == 100.0


def test_get_treasury_timeseries(db_path):
    response = client.get("/api/observatory/treasury/timeseries")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 2
    assert data[1]["balance_after"] == 400.0


def test_get_events(db_path):
    # Test offset and limit
    response = client.get("/api/observatory/events?limit=1&offset=1")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["sequence_number"] == 2
    assert data[0]["event_type"] == "vote"


def test_get_sessions_timeline(db_path):
    response = client.get("/api/observatory/sessions/timeline")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 2
    assert data[0]["session_id"] == "sess1"
    assert data[0]["state"] == "active"


def test_get_execution_heatmap(db_path):
    response = client.get("/api/observatory/execution/heatmap")
    assert response.status_code == 200
    data = response.json()
    assert "did:agent:1" in data["agents"]
    assert data["agents"]["did:agent:1"]["task1"] == "in_progress"
    assert len(data["rows"]) == 2

def test_db_not_initialized_returns_503():
    import oasis.observatory.endpoints as endpoints
    old_service = endpoints._service
    endpoints._service = None
    try:
        response = client.get("/api/observatory/summary")
    finally:
        endpoints._service = old_service
    assert response.status_code == 503

def test_get_events_pagination(db_path):
    response = client.get("/api/observatory/events?limit=1&offset=0")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["sequence_number"] == 1

def test_get_leaderboard_filtering(db_path):
    response = client.get("/api/observatory/agents/leaderboard?type=voter")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["agent_did"] == "did:agent:1"
