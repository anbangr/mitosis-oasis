"""W1–W5 — Wire ``is_conflicted`` into binding adjudication paths (Feature 2, Phase 2).

These tests verify that conflicted adjudicators are blocked from exercising
binding authority via ``/slash``, ``/freeze``, and override-panel paths.
They MUST be red before the implementation is written (TDD invariant).

Coverage target: ≥80% (100% on ``_resolve_adjudicator_did_from_signer`` and
the wired branches of ``slash_stake`` / ``freeze_agent``).
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from eth_account import Account
from fastapi.testclient import TestClient

from oasis.adjudication.schema import create_adjudication_tables
from oasis.api import app
from oasis.crypto.eip712 import sign
from oasis.crypto.typed_data import DOMAIN
from oasis.execution.schema import create_execution_tables
from oasis.governance.schema import (
    create_governance_tables,
    seed_clerks,
    seed_constitution,
)

# ---------------------------------------------------------------------------
# Seed helpers
# ---------------------------------------------------------------------------


def _seed_adjudicators(db_path: Path, adjudicators: list[dict]) -> None:
    """Seed adjudicator_registry table."""
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA foreign_keys = ON")
    for adj in adjudicators:
        conn.execute(
            "INSERT OR IGNORE INTO adjudicator_registry "
            "(adjudicator_did, eth_address, stake_amount) "
            "VALUES (?, ?, ?)",
            (
                adj["adjudicator_did"],
                adj["eth_address"],
                adj.get("stake_amount", 5000.0),
            ),
        )
    conn.commit()
    conn.close()


def _seed_agents_with_ownership(db_path: Path, agents: list[dict]) -> None:
    """Seed agent_registry with human_principal ownership and balances."""
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA foreign_keys = ON")
    for agent in agents:
        conn.execute(
            "INSERT OR IGNORE INTO agent_registry "
            "(agent_did, agent_type, display_name, human_principal, "
            "reputation_score) "
            "VALUES (?, 'producer', ?, ?, 0.5)",
            (agent["agent_did"], agent["agent_did"], agent.get("human_principal")),
        )
        conn.execute(
            "INSERT OR IGNORE INTO agent_balance "
            "(agent_did, total_balance, locked_stake, available_balance) "
            "VALUES (?, 100.0, 10.0, 90.0)",
            (agent["agent_did"],),
        )
    conn.commit()
    conn.close()


def _seed_mission(db_path: Path, session_id: str, agent_did: str) -> None:
    """Seed a legislative session and task assignment for mission inference."""
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute(
        "INSERT OR IGNORE INTO legislative_session "
        "(session_id, state, mission_budget_cap) "
        "VALUES (?, 'DEPLOYED', 1000.0)",
        (session_id,),
    )
    conn.execute(
        "INSERT OR IGNORE INTO proposal "
        "(proposal_id, session_id, proposer_did, dag_spec, "
        "token_budget_total, deadline_ms) "
        "VALUES (?, ?, ?, '{}', 1000.0, 60000)",
        ("prop-001", session_id, agent_did),
    )
    conn.execute(
        "INSERT OR IGNORE INTO dag_node "
        "(node_id, proposal_id, label, service_id, pop_tier, token_budget, "
        "timeout_ms) "
        "VALUES (?, ?, 'Test', 'test-svc', 1, 100.0, 60000)",
        ("node-001", "prop-001"),
    )
    conn.execute(
        "INSERT OR IGNORE INTO task_assignment "
        "(task_id, session_id, node_id, agent_did, status) "
        "VALUES (?, ?, ?, ?, 'committed')",
        ("task-001", session_id, "node-001", agent_did),
    )
    conn.commit()
    conn.close()


# ---------------------------------------------------------------------------
# DB + client fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def coi_db(tmp_path: Path) -> Path:
    """Single DB with governance + execution + adjudication tables."""
    db_path = tmp_path / "coi.db"
    create_governance_tables(db_path)
    seed_constitution(db_path)
    seed_clerks(db_path)
    create_execution_tables(db_path)
    create_adjudication_tables(db_path)

    from oasis.governance import endpoints as gov_ep
    from oasis.adjudication import endpoints as adj_ep

    gov_ep.init_governance_db(str(db_path))
    adj_ep.init_adjudication_db(str(db_path))

    return db_path


@pytest.fixture()
def coi_client(coi_db: Path) -> TestClient:
    return TestClient(app, raise_server_exceptions=False)


# ---------------------------------------------------------------------------
# _resolve_adjudicator_did_from_signer — 100% coverage target
# ---------------------------------------------------------------------------


def test_resolve_known_signer(coi_db: Path) -> None:
    """_resolve_adjudicator_did_from_signer returns DID for known eth address."""
    from oasis.adjudication.coi import _resolve_adjudicator_did_from_signer

    acct = Account.create()
    _seed_adjudicators(
        coi_db,
        [{"adjudicator_did": "did:adj:adj1", "eth_address": acct.address}],
    )

    result = _resolve_adjudicator_did_from_signer(
        signer_address=acct.address,
        gov_db_path=str(coi_db),
    )
    assert result == "did:adj:adj1"


def test_resolve_unknown_signer(coi_db: Path) -> None:
    """_resolve_adjudicator_did_from_signer returns None for unknown eth address."""
    from oasis.adjudication.coi import _resolve_adjudicator_did_from_signer

    acct = Account.create()
    # No adjudicators seeded

    result = _resolve_adjudicator_did_from_signer(
        signer_address=acct.address,
        gov_db_path=str(coi_db),
    )
    assert result is None


# ---------------------------------------------------------------------------
# W1 — Conflicted adjudicator's POST /slash is rejected at endpoint
# ---------------------------------------------------------------------------


def test_w1_conflict_adjudicator_slash_rejected(
    coi_db: Path,
    coi_client: TestClient,
) -> None:
    """Adj1 owns Agent1; POST /slash signed by Adj1 → HTTP 403, no decision row."""
    acct = Account.create()

    # Seed: Adj1 owns Agent1; Agent1 is in mission-X
    _seed_adjudicators(
        coi_db,
        [{"adjudicator_did": "did:adj:adj1", "eth_address": acct.address}],
    )
    _seed_agents_with_ownership(
        coi_db,
        [{"agent_did": "did:adj:agent1", "human_principal": "did:adj:adj1"}],
    )
    _seed_mission(coi_db, "mission-X", "did:adj:agent1")

    body = {
        "target_did": "did:adj:agent1",
        "amount_wei": 100,
        "reason": "test",
        "nonce": 1,
    }
    sig = sign(acct.key, DOMAIN, "Sanction", body)

    resp = coi_client.post(
        "/api/adjudication/slash",
        json=body,
        headers={
            "X-EIP712-Signature": sig.hex(),
            "X-EIP712-Signer": acct.address,
        },
    )

    assert resp.status_code == 403
    assert "recused" in resp.text.lower()

    # Verify no decision row was inserted
    conn = sqlite3.connect(str(coi_db))
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        "SELECT COUNT(*) as c FROM adjudication_decision "
        "WHERE agent_did = ? AND decision_type = 'slash'",
        ("did:adj:agent1",),
    ).fetchone()
    conn.close()
    assert row["c"] == 0


# ---------------------------------------------------------------------------
# W2 — Non-conflicted adjudicator's POST /slash succeeds
# ---------------------------------------------------------------------------


def test_w2_non_conflict_adjudicator_slash_succeeds(
    coi_db: Path,
    coi_client: TestClient,
) -> None:
    """Adj2 owns nothing; POST /slash signed by Adj2 → HTTP 200, row with issued_by_did."""
    acct = Account.create()

    _seed_adjudicators(
        coi_db,
        [{"adjudicator_did": "did:adj:adj2", "eth_address": acct.address}],
    )
    _seed_agents_with_ownership(
        coi_db,
        [{"agent_did": "did:adj:agent1", "human_principal": "did:adj:adj1"}],
    )
    _seed_mission(coi_db, "mission-X", "did:adj:agent1")

    body = {
        "target_did": "did:adj:agent1",
        "amount_wei": 100,
        "reason": "test",
        "nonce": 1,
    }
    sig = sign(acct.key, DOMAIN, "Sanction", body)

    resp = coi_client.post(
        "/api/adjudication/slash",
        json=body,
        headers={
            "X-EIP712-Signature": sig.hex(),
            "X-EIP712-Signer": acct.address,
        },
    )

    assert resp.status_code == 200
    data = resp.json()
    assert data["decision_type"] == "slash"

    # Verify row has issued_by_did = did(Adj2)
    conn = sqlite3.connect(str(coi_db))
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        "SELECT issued_by_did FROM adjudication_decision "
        "WHERE agent_did = ? AND decision_type = 'slash'",
        ("did:adj:agent1",),
    ).fetchone()
    conn.close()
    assert row is not None
    assert row["issued_by_did"] == "did:adj:adj2"


# ---------------------------------------------------------------------------
# W3 — Service-level: SanctionEngine.slash_stake raises ConflictedAdjudicatorError
# ---------------------------------------------------------------------------


def test_w3_service_slash_raises_conflicted(coi_db: Path) -> None:
    """Direct call to slash_stake with conflicted issued_by_did raises."""
    from oasis.adjudication.coi import ConflictedAdjudicatorError
    from oasis.adjudication.sanctions import SanctionEngine
    from oasis.config import PlatformConfig

    _seed_agents_with_ownership(
        coi_db,
        [{"agent_did": "did:adj:agent1", "human_principal": "did:adj:adj1"}],
    )

    engine = SanctionEngine(PlatformConfig())

    with pytest.raises(ConflictedAdjudicatorError):
        engine.slash_stake(
            agent_did="did:adj:agent1",
            amount=5.0,
            reason="test",
            db_path=coi_db,
            issued_by_did="did:adj:adj1",
            mission_id="mission-X",
        )


# ---------------------------------------------------------------------------
# W4 — Freeze path is gated identically
# ---------------------------------------------------------------------------


def test_w4_freeze_path_gated(
    coi_db: Path,
    coi_client: TestClient,
) -> None:
    """Adj1 conflicted; POST /freeze signed by Adj1 → HTTP 403, no decision row."""
    acct = Account.create()

    _seed_adjudicators(
        coi_db,
        [{"adjudicator_did": "did:adj:adj1", "eth_address": acct.address}],
    )
    _seed_agents_with_ownership(
        coi_db,
        [{"agent_did": "did:adj:agent1", "human_principal": "did:adj:adj1"}],
    )
    _seed_mission(coi_db, "mission-X", "did:adj:agent1")

    body = {
        "target_did": "did:adj:agent1",
        "amount_wei": 0,
        "reason": "test freeze",
        "nonce": 1,
    }
    sig = sign(acct.key, DOMAIN, "Sanction", body)

    resp = coi_client.post(
        "/api/adjudication/freeze",
        json=body,
        headers={
            "X-EIP712-Signature": sig.hex(),
            "X-EIP712-Signer": acct.address,
        },
    )

    assert resp.status_code == 403
    assert "recused" in resp.text.lower()

    conn = sqlite3.connect(str(coi_db))
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        "SELECT COUNT(*) as c FROM adjudication_decision "
        "WHERE agent_did = ? AND decision_type = 'freeze'",
        ("did:adj:agent1",),
    ).fetchone()
    conn.close()
    assert row["c"] == 0


# ---------------------------------------------------------------------------
# W5 — Override-panel binding path is gated identically
# ---------------------------------------------------------------------------


def test_w5_override_panel_gated(
    coi_db: Path,
    coi_client: TestClient,
) -> None:
    """Adj1 conflicted; override-panel resolve endpoint signed by Adj1 → HTTP 403."""
    acct = Account.create()

    _seed_adjudicators(
        coi_db,
        [{"adjudicator_did": "did:adj:adj1", "eth_address": acct.address}],
    )
    _seed_agents_with_ownership(
        coi_db,
        [{"agent_did": "did:adj:agent1", "human_principal": "did:adj:adj1"}],
    )

    body = {
        "target_did": "did:adj:agent1",
        "amount_wei": 0,
        "reason": "test override",
        "nonce": 1,
    }
    sig = sign(acct.key, DOMAIN, "Sanction", body)

    resp = coi_client.post(
        "/api/adjudication/override",
        json=body,
        headers={
            "X-EIP712-Signature": sig.hex(),
            "X-EIP712-Signer": acct.address,
        },
    )

    assert resp.status_code == 403
    assert "recused" in resp.text.lower()

    # Verify no override decision row was written
    conn = sqlite3.connect(str(coi_db))
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        "SELECT COUNT(*) as c FROM adjudication_decision "
        "WHERE agent_did = ? AND decision_type = 'override'",
        ("did:adj:agent1",),
    ).fetchone()
    conn.close()
    assert row["c"] == 0
