"""Shared fixtures and helpers for cross-branch E2E tests.

Provides a full 3-branch database (governance + execution + adjudication)
and helpers to drive the legislative pipeline, route tasks, execute them,
validate outputs, and settle — covering the complete lifecycle.
"""
from __future__ import annotations

import copy
import json
import sqlite3
import uuid
from pathlib import Path

import pytest

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
from oasis.adjudication.guardian import Guardian
from oasis.adjudication.treasury import Treasury


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def cross_db(tmp_path: Path) -> Path:
    """Fresh DB with governance + execution + adjudication tables."""
    db = tmp_path / "cross_branch.db"
    create_governance_tables(db)
    seed_constitution(db)
    seed_clerks(db)
    create_execution_tables(db)
    create_adjudication_tables(db)
    return db


DEFAULT_PRODUCERS = [
    {
        "agent_did": f"did:xb:producer-{i}",
        "display_name": f"XB Producer {i}",
        "reputation_score": 0.5,
    }
    for i in range(1, 6)
]


@pytest.fixture()
def producers(cross_db: Path) -> list[dict]:
    """Register 5 producer agents in the cross-branch DB."""
    conn = sqlite3.connect(str(cross_db))
    conn.execute("PRAGMA foreign_keys = ON")
    for p in DEFAULT_PRODUCERS:
        conn.execute(
            "INSERT OR IGNORE INTO agent_registry "
            "(agent_did, agent_type, display_name, human_principal, reputation_score) "
            "VALUES (?, 'producer', ?, 'human@example.com', ?)",
            (p["agent_did"], p["display_name"], p["reputation_score"]),
        )
    conn.commit()
    conn.close()
    return list(DEFAULT_PRODUCERS)


@pytest.fixture()
def config() -> PlatformConfig:
    """Default platform configuration."""
    return PlatformConfig()


# ---------------------------------------------------------------------------
# Default 3-node DAG
# ---------------------------------------------------------------------------

DEFAULT_DAG = {
    "nodes": [
        {
            "node_id": "root",
            "label": "Coordinate",
            "service_id": "coordinator",
            "pop_tier": 1,
            "token_budget": 600.0,
            "timeout_ms": 60000,
        },
        {
            "node_id": "task-a",
            "label": "Data Collection",
            "service_id": "scraper",
            "pop_tier": 1,
            "token_budget": 200.0,
            "timeout_ms": 60000,
        },
        {
            "node_id": "task-b",
            "label": "Analysis",
            "service_id": "analyzer",
            "pop_tier": 1,
            "token_budget": 200.0,
            "timeout_ms": 60000,
        },
    ],
    "edges": [
        {"from_node_id": "root", "to_node_id": "task-a"},
        {"from_node_id": "root", "to_node_id": "task-b"},
    ],
}


def _make_unique_dag(dag: dict, prefix: str) -> dict:
    """Return a copy of the DAG with node_ids prefixed to avoid PK collisions."""
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


# ---------------------------------------------------------------------------
# Helper: drive legislative pipeline to DEPLOYED
# ---------------------------------------------------------------------------

def drive_to_deployed(
    db_path: Path,
    producers: list[dict],
    *,
    session_id: str | None = None,
    dag_spec: dict | None = None,
    total_budget: float = 1000.0,
) -> dict:
    """Walk a fresh session from SESSION_INIT → DEPLOYED.

    Returns dict with session_id, proposal_id, spec_id, approved_bids, sm, dag.
    """
    db = str(db_path)
    sid = session_id or f"xb-sess-{uuid.uuid4().hex[:8]}"
    raw_dag = dag_spec or DEFAULT_DAG
    dag = _make_unique_dag(raw_dag, sid)

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
        "VALUES (?, 'SESSION_INIT', 0, ?)",
        (sid, total_budget),
    )
    conn.commit()
    conn.close()

    sm = LegislativeStateMachine(sid, db)

    # SESSION_INIT → IDENTITY_VERIFICATION
    registrar.open_session(sid, 0.1)
    result = sm.transition(LegislativeState.IDENTITY_VERIFICATION)
    assert result.allowed

    # Attest all producers
    for p in producers:
        att = IdentityAttestation(
            session_id=sid,
            agent_did=p["agent_did"],
            signature="xb-sig",
            reputation_score=p["reputation_score"],
            agent_type="producer",
        )
        res = registrar.verify_identity(att)
        assert res["passed"]

    # Insert IdentityVerificationResponse messages
    conn = sqlite3.connect(db)
    conn.execute("PRAGMA foreign_keys = ON")
    for p in producers:
        conn.execute(
            "INSERT INTO message_log "
            "(session_id, msg_type, sender_did, payload) "
            "VALUES (?, 'IdentityVerificationResponse', ?, '{}')",
            (sid, p["agent_did"]),
        )
    conn.commit()
    conn.close()

    # IDENTITY_VERIFICATION → PROPOSAL_OPEN
    result = sm.transition(LegislativeState.PROPOSAL_OPEN)
    assert result.allowed

    # Submit proposal
    proposal = DAGProposal(
        session_id=sid,
        proposer_did=producers[0]["agent_did"],
        dag_spec=dag,
        rationale="Cross-branch E2E test mission",
        token_budget_total=total_budget,
        deadline_ms=60000,
    )
    prop_result = speaker.receive_proposal(sid, proposal)
    assert prop_result["passed"]
    proposal_id = prop_result["proposal_id"]

    # PROPOSAL_OPEN → BIDDING_OPEN
    result = sm.transition(LegislativeState.BIDDING_OPEN)
    assert result.allowed

    # Submit bids — distribute across producers
    nodes = dag["nodes"]
    for idx, node in enumerate(nodes):
        bidder = producers[idx % len(producers)]
        bid = TaskBid(
            session_id=sid,
            task_node_id=node["node_id"],
            bidder_did=bidder["agent_did"],
            service_id=node["service_id"],
            proposed_code_hash="abcdef1234567890",
            stake_amount=0.5,
            estimated_latency_ms=5000,
            pop_tier_acceptance=node.get("pop_tier", 1),
        )
        bid_result = regulator.receive_bid(sid, bid)
        assert bid_result["passed"]

    # BIDDING_OPEN → REGULATORY_REVIEW
    result = sm.transition(LegislativeState.REGULATORY_REVIEW)
    assert result.allowed

    # Evaluate bids
    eval_result = regulator.evaluate_bids(sid)

    # REGULATORY_REVIEW → CODIFICATION
    result = sm.transition(LegislativeState.CODIFICATION)
    assert result.allowed

    # Compile and validate spec
    conn = sqlite3.connect(db)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.row_factory = sqlite3.Row
    bid_rows = conn.execute(
        "SELECT * FROM bid WHERE session_id = ? AND status = 'approved'",
        (sid,),
    ).fetchall()
    approved_bids_list = [dict(b) for b in bid_rows]
    conn.close()

    spec = codifier.compile_spec(sid, proposal, approved_bids_list)
    val_result = codifier.run_constitutional_validation(spec)
    assert val_result.passed

    # CODIFICATION → AWAITING_APPROVAL
    result = sm.transition(LegislativeState.AWAITING_APPROVAL)
    assert result.allowed

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

    result = sm.transition(
        LegislativeState.DEPLOYED,
        signatures={"proposer": speaker_sig["speaker_signature"], "regulator": reg_sig},
    )
    assert result.allowed

    return {
        "session_id": sid,
        "proposal_id": proposal_id,
        "spec_id": spec.validation_proof,
        "approved_bids": eval_result.get("approved_bids", []),
        "sm": sm,
        "spec": spec,
        "dag": dag,
    }


# ---------------------------------------------------------------------------
# Helper: route + commit + execute + validate + settle all tasks
# ---------------------------------------------------------------------------

def execute_all_tasks(
    db_path: Path,
    session_id: str,
    config: PlatformConfig,
) -> list[dict]:
    """Route tasks, commit, execute (synthetic), and settle them.

    Returns list of settlement results.
    """
    db = str(db_path)

    # Route tasks
    tasks = route_tasks(session_id, db)

    dispatcher = ExecutionDispatcher(config, db)
    settler = SettlementCalculator(config)
    settlements = []

    for task in tasks:
        task_id = task["task_id"]

        # Commit
        commit_to_task(task_id, task["agent_did"], db)

        # Dispatch (synthetic mode generates + validates)
        dispatch_result = dispatcher.dispatch_task(task_id)

        # Settle
        settlement = settler.settle_task(task_id, db)
        settlements.append(settlement)

    return settlements


def execute_all_tasks_llm(
    db_path: Path,
    session_id: str,
    config: PlatformConfig,
) -> list[dict]:
    """Route tasks, commit, dispatch (LLM mode), submit output, and settle.

    Returns list of settlement results.
    """
    db = str(db_path)

    tasks = route_tasks(session_id, db)

    dispatcher = ExecutionDispatcher(config, db)
    settler = SettlementCalculator(config)
    settlements = []

    for task in tasks:
        task_id = task["task_id"]
        agent_did = task["agent_did"]

        # Commit
        commit_to_task(task_id, agent_did, db)

        # Dispatch (LLM mode puts task in 'executing' state)
        dispatcher.dispatch_task(task_id)

        # Submit output via API
        output_data = json.dumps({
            "task_id": task_id,
            "result": f"LLM output for {task_id}",
            "status": "success",
            "metrics": {"accuracy": 0.9, "completeness": 0.85},
        })
        dispatcher.receive_output(task_id, output_data, agent_did)

        # Settle
        settlement = settler.settle_task(task_id, db)
        settlements.append(settlement)

    return settlements
