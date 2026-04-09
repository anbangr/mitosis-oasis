"""E2E: Bad output → guardian alert → override panel freeze → stake slash → reputation reduction."""
from __future__ import annotations

import json
import sqlite3

from oasis.config import PlatformConfig
from oasis.execution.commitment import commit_to_task
from oasis.execution.router import route_tasks
from oasis.execution.runner import ExecutionDispatcher
from oasis.adjudication.guardian import Guardian
from oasis.adjudication.override_panel import OverridePanel
from oasis.adjudication.sanctions import SanctionEngine
from oasis.adjudication.settlement import SettlementCalculator
from oasis.governance.state_machine import LegislativeState

from .conftest import drive_to_deployed


def test_guardian_freeze_pipeline(cross_db, producers):
    """Bad output triggers: guardian alert → override freeze → slash → rep reduction."""
    config = PlatformConfig(
        execution_mode="llm",
        freeze_threshold=0.5,   # quality < 0.5 triggers FREEZE
        warn_threshold=0.3,
    )

    # Phase 1: Legislative → DEPLOYED
    result = drive_to_deployed(cross_db, producers)
    assert result["sm"].current_state == LegislativeState.DEPLOYED
    db = str(cross_db)
    sid = result["session_id"]

    # Phase 2: Route tasks
    tasks = route_tasks(sid, db)
    assert len(tasks) > 0

    # Pick first task, commit
    task = tasks[0]
    task_id = task["task_id"]
    agent_did = task["agent_did"]

    commit_to_task(task_id, agent_did, db)

    # Dispatch in LLM mode
    dispatcher = ExecutionDispatcher(config, db)
    dispatcher.dispatch_task(task_id)

    # Submit BAD output (malicious payload with schema failure)
    bad_output = json.dumps({
        "task_id": task_id,
        "wrong_field": "this is bad data",
        # Missing 'result' and 'status' — schema failure
    })
    output_result = dispatcher.receive_output(task_id, bad_output, agent_did)

    # Validation should have failed
    validation = output_result.get("validation", {})
    assert not validation.get("schema_valid", True)

    # Phase 3: Guardian processes the validation
    guardian = Guardian(config, db)
    alert = guardian.process_validation({
        "task_id": task_id,
        "schema_valid": False,
        "timeout_valid": True,
        "quality_score": 0.0,
    })
    assert alert is not None
    assert alert.severity in ("CRITICAL", "WARNING")

    # Override panel evaluates alert
    panel = OverridePanel(config, db)
    decision = panel.decide({
        "type": "alert",
        "alert_id": alert.alert_id,
        "task_id": task_id,
        "quality_score": 0.0,
        "agent_did": agent_did,
    })
    # With quality 0.0 < freeze_threshold 0.5, should FREEZE
    assert decision.decision_type in ("freeze", "slash")

    # Apply sanction: freeze agent
    sanctions = SanctionEngine(config)
    freeze_decision = sanctions.freeze_agent(agent_did, "Bad output detected", db)
    assert freeze_decision.decision_type == "freeze"

    # Verify agent is frozen
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    agent = conn.execute(
        "SELECT active FROM agent_registry WHERE agent_did = ?",
        (agent_did,),
    ).fetchone()
    conn.close()
    assert agent["active"] == 0

    # Slash stake
    slash_decision = sanctions.slash_stake(agent_did, 5.0, "Quality violation", db)
    assert slash_decision.decision_type == "slash"

    # Reduce reputation
    rep_decision = sanctions.reduce_reputation(agent_did, 0.1, db)
    assert rep_decision.decision_type == "reputation_reduction"

    # Verify reputation decreased
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    agent = conn.execute(
        "SELECT reputation_score FROM agent_registry WHERE agent_did = ?",
        (agent_did,),
    ).fetchone()
    conn.close()
    assert agent["reputation_score"] < 0.5  # Started at 0.5
