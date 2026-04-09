"""E2E: Run 10 tasks, verify fees + slashing + subsidies balance correctly."""
from __future__ import annotations

import copy
import sqlite3

from oasis.config import PlatformConfig
from oasis.adjudication.sanctions import SanctionEngine
from oasis.adjudication.treasury import Treasury
from oasis.governance.state_machine import LegislativeState

from .conftest import drive_to_deployed, execute_all_tasks, _make_unique_dag


# A larger DAG with 10 nodes for treasury balance testing.
# Root node budget covers all children; children are leaves.
TEN_TASK_DAG = {
    "nodes": [
        {
            "node_id": "treasury-root",
            "label": "Root Coordinator",
            "service_id": "coordinator",
            "pop_tier": 1,
            "token_budget": 1000.0,
            "timeout_ms": 60000,
        },
    ] + [
        {
            "node_id": f"treasury-task-{i}",
            "label": f"Task {i}",
            "service_id": f"svc-{i}",
            "pop_tier": 1,
            "token_budget": 100.0,
            "timeout_ms": 60000,
        }
        for i in range(1, 10)
    ],
    "edges": [
        {"from_node_id": "treasury-root", "to_node_id": f"treasury-task-{i}"}
        for i in range(1, 10)
    ],
}


def test_treasury_balance_after_10_tasks(cross_db, producers):
    """Run 10 tasks and verify treasury accounting is correct."""
    config = PlatformConfig(
        execution_mode="synthetic",
        synthetic_quality="perfect",
        protocol_fee_rate=0.02,
        insurance_fee_rate=0.01,
    )

    # Legislative → DEPLOYED with 10-task DAG (root=1000 + 9*100 = 1900)
    result = drive_to_deployed(
        cross_db, producers,
        dag_spec=TEN_TASK_DAG,
        total_budget=1900.0,
    )
    assert result["sm"].current_state == LegislativeState.DEPLOYED

    # Execute all 10 tasks (1 root + 9 children)
    settlements = execute_all_tasks(cross_db, result["session_id"], config)
    assert len(settlements) == 10

    db = str(cross_db)

    # Verify treasury balance
    treasury = Treasury(db)
    summary = treasury.get_summary()

    total_protocol_fees = sum(s.protocol_fee for s in settlements)
    total_insurance_fees = sum(s.insurance_fee for s in settlements)
    total_subsidies = sum(s.treasury_subsidy for s in settlements)

    # Inflows should match
    assert abs(summary.inflows.get("protocol_fee", 0) - total_protocol_fees) < 0.01
    assert abs(summary.inflows.get("insurance_fee", 0) - total_insurance_fees) < 0.01

    # Net balance = inflows - outflows
    expected_net = total_protocol_fees + total_insurance_fees - total_subsidies
    assert abs(summary.net_balance - expected_net) < 0.01

    # Now add a slash to test slash proceeds
    sanctions = SanctionEngine(config)
    agent_did = producers[0]["agent_did"]

    # Ensure agent has locked stake
    conn = sqlite3.connect(db)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute(
        "INSERT OR IGNORE INTO agent_balance "
        "(agent_did, total_balance, locked_stake, available_balance) "
        "VALUES (?, 100.0, 10.0, 90.0)",
        (agent_did,),
    )
    conn.execute(
        "UPDATE agent_balance SET locked_stake = 10.0 WHERE agent_did = ?",
        (agent_did,),
    )
    conn.commit()
    conn.close()

    sanctions.slash_stake(agent_did, 5.0, "Test slash", db)

    # Treasury should now include slash_proceeds
    summary_after = treasury.get_summary()
    assert summary_after.inflows.get("slash_proceeds", 0) >= 5.0
    assert summary_after.net_balance > summary.net_balance
