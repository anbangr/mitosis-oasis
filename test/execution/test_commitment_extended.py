import sqlite3
import pytest
import tempfile
import os

from oasis.execution.commitment import commit_to_task, validate_commitment, release_stake

@pytest.fixture
def db_path():
    fd, path = tempfile.mkstemp(suffix=".sqlite")
    os.close(fd)
    
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA foreign_keys = ON")
    
    # Create required schemas for commitment
    conn.executescript("""
        CREATE TABLE task_assignment (node_id TEXT, task_id TEXT PRIMARY KEY, agent_did TEXT, status TEXT, session_id TEXT);
        CREATE TABLE agent_registry (agent_did TEXT PRIMARY KEY, active BOOLEAN);
        CREATE TABLE agent_balance (agent_did TEXT PRIMARY KEY, total_balance REAL, locked_stake REAL, available_balance REAL);
        CREATE TABLE bid (session_id TEXT, task_node_id TEXT, bidder_did TEXT, stake_amount REAL, status TEXT);
        CREATE TABLE task_commitment (commitment_id TEXT PRIMARY KEY, task_id TEXT, agent_did TEXT, stake_amount REAL);
    """)
    
    # Seed initial test data
    conn.executescript("""
        INSERT INTO agent_registry VALUES ('agent_1', 1);
        INSERT INTO agent_registry VALUES ('agent_2', 0);
        
        INSERT INTO agent_balance VALUES ('agent_1', 100.0, 0.0, 100.0);
        
        -- Task 1: standard pending task assigned to agent_1
        INSERT INTO task_assignment VALUES ('node_1', 'task_1', 'agent_1', 'pending', 'sess_1');
        INSERT INTO bid VALUES ('sess_1', 'node_1', 'agent_1', 10.0, 'approved');
        
        -- Task 2: assigned to inactive agent
        INSERT INTO task_assignment VALUES ('node_2', 'task_2', 'agent_2', 'pending', 'sess_1');
        
        -- Task 3: not pending
        INSERT INTO task_assignment VALUES ('node_3', 'task_3', 'agent_1', 'settled', 'sess_1');
        
        -- Task 4: insufficient balance (bid stake = 200, balance = 100)
        INSERT INTO task_assignment VALUES ('node_4', 'task_4', 'agent_1', 'pending', 'sess_1');
        INSERT INTO bid VALUES ('sess_1', 'node_4', 'agent_1', 200.0, 'approved');
    """)
    conn.commit()
    conn.close()
    
    yield path
    os.remove(path)


def test_commit_to_task_success(db_path):
    res = commit_to_task("task_1", "agent_1", db_path)
    assert res["status"] == "committed"
    assert res["agent_did"] == "agent_1"
    assert res["stake_amount"] == 10.0
    
    # Verify DB state
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    bal = conn.execute("SELECT * FROM agent_balance WHERE agent_did = 'agent_1'").fetchone()
    assert bal["locked_stake"] == 10.0
    assert bal["available_balance"] == 90.0
    
    task = conn.execute("SELECT * FROM task_assignment WHERE task_id = 'task_1'").fetchone()
    assert task["status"] == "committed"
    conn.close()


def test_commit_to_task_inactive_agent(db_path):
    with pytest.raises(ValueError, match="is not active"):
        commit_to_task("task_2", "agent_2", db_path)


def test_commit_to_task_wrong_assignee(db_path):
    with pytest.raises(ValueError, match="not assigned to task"):
        commit_to_task("task_1", "agent_2", db_path)


def test_commit_to_task_not_pending(db_path):
    with pytest.raises(ValueError, match="is in state 'settled'"):
        commit_to_task("task_3", "agent_1", db_path)


def test_commit_to_task_insufficient_balance(db_path):
    with pytest.raises(ValueError, match="Insufficient balance"):
        commit_to_task("task_4", "agent_1", db_path)


def test_validate_commitment(db_path):
    # First, make a commitment
    res = commit_to_task("task_1", "agent_1", db_path)
    
    val = validate_commitment("task_1", db_path)
    assert val["valid"] is True
    assert len(val["errors"]) == 0
    
    # Manually invalidate it by modifying status
    conn = sqlite3.connect(db_path)
    conn.execute("UPDATE task_assignment SET status = 'pending' WHERE task_id = 'task_1'")
    conn.commit()
    conn.close()
    
    val = validate_commitment("task_1", db_path)
    assert val["valid"] is False
    assert "expected 'committed'" in val["errors"][0]


def test_release_stake(db_path):
    # Setup
    commit_to_task("task_1", "agent_1", db_path)
    
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    bal1 = conn.execute("SELECT * FROM agent_balance WHERE agent_did = 'agent_1'").fetchone()
    assert bal1["available_balance"] == 90.0
    assert bal1["locked_stake"] == 10.0
    conn.close()
    
    # Act
    res = release_stake("task_1", db_path)
    assert res["released_amount"] == 10.0
    
    # Verify unlocked
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    bal2 = conn.execute("SELECT * FROM agent_balance WHERE agent_did = 'agent_1'").fetchone()
    assert bal2["available_balance"] == 100.0
    assert bal2["locked_stake"] == 0.0
    conn.close()

def test_release_stake_no_commitment(db_path):
    with pytest.raises(ValueError, match="No commitment found"):
        release_stake("task_2", db_path)
