"""Regression coverage for COI enforcement with split adjudication/governance DBs."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from eth_account import Account
from fastapi.testclient import TestClient

from oasis.adjudication import endpoints as adj_ep
from oasis.adjudication.schema import create_adjudication_tables
from oasis.api import app
from oasis.crypto.eip712 import sign
from oasis.crypto.typed_data import DOMAIN
from oasis.execution.schema import create_execution_tables
from oasis.governance import endpoints as gov_ep
from oasis.governance.schema import (
    create_governance_tables,
    seed_clerks,
    seed_constitution,
)


def _init_split_dbs(tmp_path: Path) -> tuple[Path, Path]:
    adj_db_path = tmp_path / "adj.sqlite"
    gov_db_path = tmp_path / "gov.sqlite"

    create_adjudication_tables(adj_db_path)
    create_governance_tables(gov_db_path)
    seed_constitution(gov_db_path)
    seed_clerks(gov_db_path)
    create_execution_tables(gov_db_path)

    adj_ep.init_adjudication_db(str(adj_db_path))
    gov_ep.init_governance_db(str(gov_db_path))
    app.state.gov_db_path = str(gov_db_path)
    return adj_db_path, gov_db_path


def _seed_mission(gov_db_path: Path, *, session_id: str, agent_did: str) -> None:
    conn = sqlite3.connect(str(gov_db_path))
    try:
        conn.execute(
            "INSERT OR IGNORE INTO agent_registry "
            "(agent_did, agent_type, display_name, human_principal) "
            "VALUES (?, 'producer', ?, ?)",
            (agent_did, agent_did, "did:adj:owner"),
        )
        conn.execute(
            "INSERT OR IGNORE INTO legislative_session "
            "(session_id, state, mission_budget_cap) VALUES (?, 'DEPLOYED', 1000.0)",
            (session_id,),
        )
        conn.execute(
            "INSERT OR IGNORE INTO proposal "
            "(proposal_id, session_id, proposer_did, dag_spec, token_budget_total, deadline_ms) "
            "VALUES ('prop-two-db', ?, ?, '{}', 1000.0, 60000)",
            (session_id, agent_did),
        )
        conn.execute(
            "INSERT OR IGNORE INTO dag_node "
            "(node_id, proposal_id, label, pop_tier, token_budget, timeout_ms) "
            "VALUES ('node-two-db', 'prop-two-db', 'Test', 1, 100.0, 60000)",
        )
        conn.execute(
            "INSERT OR IGNORE INTO task_assignment "
            "(task_id, session_id, node_id, agent_did, status) "
            "VALUES ('task-two-db', ?, 'node-two-db', ?, 'committed')",
            (session_id, agent_did),
        )
        conn.commit()
    finally:
        conn.close()


def test_two_db_non_conflicted_slash_records_decision(tmp_path: Path) -> None:
    adj_db_path, gov_db_path = _init_split_dbs(tmp_path)
    acct = Account.create()

    conn = sqlite3.connect(str(adj_db_path))
    try:
        conn.execute(
            "INSERT INTO adjudicator_registry (adjudicator_did, eth_address) "
            "VALUES (?, ?)",
            ("did:adj:reviewer", acct.address),
        )
        conn.commit()
    finally:
        conn.close()

    conn = sqlite3.connect(str(gov_db_path))
    try:
        conn.execute(
            "INSERT OR IGNORE INTO agent_registry (agent_did, agent_type, display_name) "
            "VALUES ('did:adj:reviewer', 'producer', 'did:adj:reviewer')",
        )
        conn.commit()
    finally:
        conn.close()

    _seed_mission(gov_db_path, session_id="mission-X", agent_did="did:adj:agent1")

    body = {
        "target_did": "did:adj:agent1",
        "amount_wei": 100,
        "reason": "two-db slash",
        "nonce": 1,
        "mission_id": "mission-X",
    }
    sig = sign(acct.key, DOMAIN, "Sanction", body)

    try:
        resp = TestClient(app, raise_server_exceptions=False).post(
            "/api/adjudication/slash",
            json=body,
            headers={
                "X-EIP712-Signature": sig.hex(),
                "X-EIP712-Signer": acct.address,
            },
        )
    finally:
        delattr(app.state, "gov_db_path")

    assert resp.status_code == 200

    conn = sqlite3.connect(str(adj_db_path))
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute(
            "SELECT issued_by_did FROM adjudication_decision "
            "WHERE agent_did = ? AND decision_type = 'slash'",
            ("did:adj:agent1",),
        ).fetchone()
    finally:
        conn.close()

    assert row is not None
    assert row["issued_by_did"] == "did:adj:reviewer"
