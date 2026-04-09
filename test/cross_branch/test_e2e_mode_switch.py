"""E2E: Switch between LLM and synthetic execution mode mid-experiment."""
from __future__ import annotations

import json
import sqlite3

from oasis.config import PlatformConfig
from oasis.execution.commitment import commit_to_task
from oasis.execution.router import route_tasks
from oasis.execution.runner import ExecutionDispatcher
from oasis.adjudication.settlement import SettlementCalculator
from oasis.governance.state_machine import LegislativeState

from .conftest import drive_to_deployed


def test_mode_switch_mid_experiment(cross_db, producers):
    """Switch between LLM and synthetic mode mid-experiment via config."""
    # Start in synthetic mode
    config_synthetic = PlatformConfig(
        execution_mode="synthetic",
        synthetic_quality="perfect",
    )

    # Legislative → DEPLOYED
    result = drive_to_deployed(cross_db, producers)
    assert result["sm"].current_state == LegislativeState.DEPLOYED
    db = str(cross_db)
    sid = result["session_id"]

    # Route all tasks
    tasks = route_tasks(sid, db)
    assert len(tasks) == 3

    # --- Execute first task in SYNTHETIC mode ---
    task_0 = tasks[0]
    commit_to_task(task_0["task_id"], task_0["agent_did"], db)

    dispatcher_synth = ExecutionDispatcher(config_synthetic, db)
    result_0 = dispatcher_synth.dispatch_task(task_0["task_id"])
    assert result_0["mode"] == "synthetic"

    settler = SettlementCalculator(config_synthetic)
    settle_0 = settler.settle_task(task_0["task_id"], db)
    assert settle_0.final_reward > 0

    # --- Switch to LLM mode for remaining tasks ---
    config_llm = PlatformConfig(execution_mode="llm")
    dispatcher_llm = ExecutionDispatcher(config_llm, db)
    settler_llm = SettlementCalculator(config_llm)

    for task in tasks[1:]:
        task_id = task["task_id"]
        agent_did = task["agent_did"]

        commit_to_task(task_id, agent_did, db)
        dispatch_result = dispatcher_llm.dispatch_task(task_id)
        assert dispatch_result["mode"] == "llm"

        # Submit output manually (LLM mode)
        output_data = json.dumps({
            "task_id": task_id,
            "result": f"LLM output for {task_id}",
            "status": "success",
            "metrics": {"accuracy": 0.85, "completeness": 0.9},
        })
        dispatcher_llm.receive_output(task_id, output_data, agent_did)

        settle = settler_llm.settle_task(task_id, db)
        assert settle.final_reward > 0

    # All 3 tasks settled
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    settled = conn.execute(
        "SELECT COUNT(*) AS cnt FROM settlement WHERE task_id IN "
        "(SELECT task_id FROM task_assignment WHERE session_id = ?)",
        (sid,),
    ).fetchone()
    conn.close()
    assert settled["cnt"] == 3
