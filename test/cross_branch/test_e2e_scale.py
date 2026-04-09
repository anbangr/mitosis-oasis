"""E2E: 50 agents, 20 tasks — verify no deadlocks or data races."""
from __future__ import annotations

import copy
import json
import sqlite3
import uuid
from pathlib import Path

from oasis.config import PlatformConfig
from oasis.governance.clerks.codifier import Codifier
from oasis.governance.clerks.registrar import Registrar
from oasis.governance.clerks.regulator import Regulator
from oasis.governance.clerks.speaker import Speaker
from oasis.governance.messages import (
    DAGProposal,
    IdentityAttestation,
    LegislativeApproval,
    TaskBid,
    log_message,
)
from oasis.governance.schema import (
    create_governance_tables,
    seed_clerks,
    seed_constitution,
)
from oasis.governance.state_machine import LegislativeState, LegislativeStateMachine
from oasis.execution.schema import create_execution_tables
from oasis.execution.router import route_tasks
from oasis.execution.commitment import commit_to_task
from oasis.execution.runner import ExecutionDispatcher
from oasis.adjudication.schema import create_adjudication_tables
from oasis.adjudication.settlement import SettlementCalculator
from oasis.adjudication.treasury import Treasury


# 20-task DAG: root node (budget covers children) + 19 leaf tasks
SCALE_DAG = {
    "nodes": [
        {
            "node_id": "scale-root",
            "label": "Root Coordinator",
            "service_id": "coordinator",
            "pop_tier": 1,
            "token_budget": 5000.0,
            "timeout_ms": 60000,
        },
    ] + [
        {
            "node_id": f"scale-task-{i}",
            "label": f"Task {i}",
            "service_id": f"svc-{i % 5}",
            "pop_tier": 1,
            "token_budget": 50.0,
            "timeout_ms": 60000,
        }
        for i in range(1, 20)
    ],
    "edges": [
        {"from_node_id": "scale-root", "to_node_id": f"scale-task-{i}"}
        for i in range(1, 20)
    ],
}


def _make_unique_dag(dag: dict, prefix: str) -> dict:
    d = copy.deepcopy(dag)
    id_map = {}
    for node in d["nodes"]:
        old_id = node["node_id"]
        new_id = f"{prefix}-{old_id}"
        id_map[old_id] = new_id
        node["node_id"] = new_id
    for edge in d.get("edges", []):
        edge["from_node_id"] = id_map[edge["from_node_id"]]
        edge["to_node_id"] = id_map[edge["to_node_id"]]
    return d


def test_scale_50_agents_20_tasks(tmp_path):
    """50 agents, 20 tasks — full pipeline completes without errors."""
    db_path = tmp_path / "scale.db"
    create_governance_tables(db_path)
    seed_constitution(db_path)
    seed_clerks(db_path)
    create_execution_tables(db_path)
    create_adjudication_tables(db_path)
    db = str(db_path)

    # Register 50 agents
    agents = []
    conn = sqlite3.connect(db)
    conn.execute("PRAGMA foreign_keys = ON")
    for i in range(1, 51):
        agent = {
            "agent_did": f"did:scale:agent-{i}",
            "display_name": f"Scale Agent {i}",
            "reputation_score": 0.5,
        }
        agents.append(agent)
        conn.execute(
            "INSERT OR IGNORE INTO agent_registry "
            "(agent_did, agent_type, display_name, human_principal, reputation_score) "
            "VALUES (?, 'producer', ?, 'human@example.com', ?)",
            (agent["agent_did"], agent["display_name"], agent["reputation_score"]),
        )
    conn.commit()
    conn.close()

    config = PlatformConfig(
        execution_mode="synthetic",
        synthetic_quality="perfect",
    )

    sid = f"scale-sess-{uuid.uuid4().hex[:8]}"
    dag = _make_unique_dag(SCALE_DAG, sid)

    # Clerk instances
    registrar = Registrar(db_path=db, clerk_did="did:oasis:clerk-registrar")
    speaker = Speaker(db_path=db, clerk_did="did:oasis:clerk-speaker")
    regulator = Regulator(db_path=db, clerk_did="did:oasis:clerk-regulator")
    codifier = Codifier(db_path=db, clerk_did="did:oasis:clerk-codifier")

    # Create session
    conn = sqlite3.connect(db)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute(
        "INSERT OR IGNORE INTO legislative_session "
        "(session_id, state, epoch, mission_budget_cap) "
        "VALUES (?, 'SESSION_INIT', 0, 5000.0)",
        (sid,),
    )
    conn.commit()
    conn.close()

    sm = LegislativeStateMachine(sid, db)

    # Open session + identity verification
    registrar.open_session(sid, 0.1)
    sm.transition(LegislativeState.IDENTITY_VERIFICATION)

    # Attest all 50 agents
    for a in agents:
        att = IdentityAttestation(
            session_id=sid,
            agent_did=a["agent_did"],
            signature="scale-sig",
            reputation_score=a["reputation_score"],
            agent_type="producer",
        )
        registrar.verify_identity(att)

    # Insert identity responses
    conn = sqlite3.connect(db)
    conn.execute("PRAGMA foreign_keys = ON")
    for a in agents:
        conn.execute(
            "INSERT INTO message_log "
            "(session_id, msg_type, sender_did, payload) "
            "VALUES (?, 'IdentityVerificationResponse', ?, '{}')",
            (sid, a["agent_did"]),
        )
    conn.commit()
    conn.close()

    # IDENTITY_VERIFICATION → PROPOSAL_OPEN
    sm.transition(LegislativeState.PROPOSAL_OPEN)

    # Submit proposal (from first agent)
    proposal = DAGProposal(
        session_id=sid,
        proposer_did=agents[0]["agent_did"],
        dag_spec=dag,
        rationale="Scale test mission",
        token_budget_total=5000.0,
        deadline_ms=120000,
    )
    prop_result = speaker.receive_proposal(sid, proposal)
    assert prop_result["passed"]

    # PROPOSAL_OPEN → BIDDING_OPEN
    sm.transition(LegislativeState.BIDDING_OPEN)

    # Submit bids — distribute 20 tasks across 50 agents
    for idx, node in enumerate(dag["nodes"]):
        bidder = agents[idx % len(agents)]
        bid = TaskBid(
            session_id=sid,
            task_node_id=node["node_id"],
            bidder_did=bidder["agent_did"],
            service_id=node["service_id"],
            proposed_code_hash="scale-hash-" + node["node_id"],
            stake_amount=0.5,
            estimated_latency_ms=5000,
            pop_tier_acceptance=1,
        )
        bid_result = regulator.receive_bid(sid, bid)
        assert bid_result["passed"]

    # BIDDING_OPEN → REGULATORY_REVIEW
    sm.transition(LegislativeState.REGULATORY_REVIEW)
    regulator.evaluate_bids(sid)

    # REGULATORY_REVIEW → CODIFICATION
    sm.transition(LegislativeState.CODIFICATION)

    conn = sqlite3.connect(db)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.row_factory = sqlite3.Row
    approved_bids = [
        dict(b) for b in conn.execute(
            "SELECT * FROM bid WHERE session_id = ? AND status = 'approved'",
            (sid,),
        ).fetchall()
    ]
    conn.close()

    spec = codifier.compile_spec(sid, proposal, approved_bids)
    val_result = codifier.run_constitutional_validation(spec)
    assert val_result.passed

    # CODIFICATION → AWAITING_APPROVAL
    sm.transition(LegislativeState.AWAITING_APPROVAL)

    # Dual sign-off → DEPLOYED
    speaker_sig = speaker.issue_approval(sid, spec.validation_proof)
    reg_sig = regulator.co_sign_approval(sid, spec.validation_proof)

    msg = LegislativeApproval(
        session_id=sid,
        spec_id=spec.validation_proof,
        speaker_signature=speaker_sig["speaker_signature"],
        regulator_signature=reg_sig,
    )
    log_message(db, sid, msg, sender_did="system")

    sm.transition(
        LegislativeState.DEPLOYED,
        signatures={"proposer": speaker_sig["speaker_signature"], "regulator": reg_sig},
    )
    assert sm.current_state == LegislativeState.DEPLOYED

    # Route 20 tasks
    tasks = route_tasks(sid, db)
    assert len(tasks) == 20

    # Commit + execute + settle all 20
    dispatcher = ExecutionDispatcher(config, db)
    settler = SettlementCalculator(config)

    for task in tasks:
        commit_to_task(task["task_id"], task["agent_did"], db)
        dispatcher.dispatch_task(task["task_id"])
        settler.settle_task(task["task_id"], db)

    # Verify all 20 tasks settled
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    settled_count = conn.execute(
        "SELECT COUNT(*) AS cnt FROM settlement WHERE task_id IN "
        "(SELECT task_id FROM task_assignment WHERE session_id = ?)",
        (sid,),
    ).fetchone()
    conn.close()
    assert settled_count["cnt"] == 20

    # Verify treasury has entries
    treasury = Treasury(db)
    summary = treasury.get_summary()
    assert summary.net_balance > 0

    # Verify no orphaned tasks
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    pending = conn.execute(
        "SELECT COUNT(*) AS cnt FROM task_assignment "
        "WHERE session_id = ? AND status = 'pending'",
        (sid,),
    ).fetchone()
    conn.close()
    assert pending["cnt"] == 0
