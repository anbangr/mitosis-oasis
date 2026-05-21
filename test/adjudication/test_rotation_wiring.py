"""RW1–RW4 — Wire ``enforce_rotation`` into binding adjudication paths (Feature 3, Phase 2).

These tests verify that adjudicators who have reached the max_consecutive
limit for a given decision_type are blocked from exercising binding authority
via ``/freeze`` (and by extension ``/slash`` and override-panel paths).
They MUST be red before the implementation is written (TDD invariant).

Coverage target: ≥80% (100% on the new rotation-gated branch of
``slash_stake`` / ``freeze_agent`` / override path).
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


def _seed_constitution_rotation_param(db_path: Path, max_consecutive: int = 2) -> None:
    """Insert rotation_max_consecutive into the constitution table."""
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute(
        "INSERT OR IGNORE INTO constitution "
        "(param_name, param_value, param_type, description) "
        "VALUES (?, ?, ?, ?)",
        (
            "rotation_max_consecutive",
            float(max_consecutive),
            "integer",
            "Maximum consecutive same-type decisions per adjudicator",
        ),
    )
    conn.commit()
    conn.close()


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


def _seed_agents(db_path: Path, agents: list[dict]) -> None:
    """Seed agent_registry with balances."""
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


def _seed_decisions(
    db_path: Path,
    decisions: list[tuple[str, str, str]],
) -> None:
    """Insert adjudication_decision rows.

    Each tuple is (decision_type, issued_by_did, agent_did).
    Array index 0 is the OLDEST decision, last element is the most recent.
    """
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA foreign_keys = ON")
    total = len(decisions)
    for idx, (decision_type, issued_by_did, agent_did) in enumerate(decisions):
        offset = total - 1 - idx
        conn.execute(
            "INSERT INTO adjudication_decision "
            "(decision_id, agent_did, decision_type, severity, reason, "
            "layer1_result, issued_by_did, created_at) "
            "VALUES (?, ?, ?, 'INFO', 'test reason', 'test', ?, "
            "datetime('now', '-{} seconds'))".format(offset),
            (
                f"dec-{idx:04d}",
                agent_did,
                decision_type,
                issued_by_did,
            ),
        )
    conn.commit()
    conn.close()


# ---------------------------------------------------------------------------
# DB + client fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def rot_db(tmp_path: Path) -> Path:
    """Single DB with governance + execution + adjudication tables."""
    db_path = tmp_path / "rot.db"
    create_governance_tables(db_path)
    seed_constitution(db_path)
    seed_clerks(db_path)
    create_execution_tables(db_path)
    create_adjudication_tables(db_path)

    from oasis.governance import endpoints as gov_ep
    from oasis.adjudication import endpoints as adj_ep

    gov_ep.init_governance_db(str(db_path))
    adj_ep.init_adjudication_db(str(db_path))

    _seed_constitution_rotation_param(db_path, max_consecutive=2)

    return db_path


@pytest.fixture()
def rot_client(rot_db: Path) -> TestClient:
    return TestClient(app, raise_server_exceptions=False)


# ---------------------------------------------------------------------------
# RW1 — Third consecutive same-type freeze by same adjudicator is rejected
# ---------------------------------------------------------------------------


def test_rw1_third_consecutive_freeze_rejected_at_endpoint(
    rot_db: Path,
    rot_client: TestClient,
) -> None:
    """Adj1 issued 2 consecutive freezes; POST /freeze by Adj1 → HTTP 409, no row."""
    acct = Account.create()

    _seed_adjudicators(
        rot_db,
        [{"adjudicator_did": "did:adj:adj1", "eth_address": acct.address}],
    )
    _seed_agents(
        rot_db,
        [
            {"agent_did": "did:adj:agent1"},
            {"agent_did": "did:adj:agent2"},
            {"agent_did": "did:adj:agent3"},
        ],
    )

    # Seed 2 consecutive freezes by Adj1 (oldest first)
    _seed_decisions(
        rot_db,
        [
            ("freeze", "did:adj:adj1", "did:adj:agent1"),
            ("freeze", "did:adj:adj1", "did:adj:agent2"),
        ],
    )

    body = {
        "target_did": "did:adj:agent3",
        "amount_wei": 0,
        "reason": "test freeze rw1",
        "nonce": 1,
    }
    sig = sign(acct.key, DOMAIN, "Sanction", body)

    resp = rot_client.post(
        "/api/adjudication/freeze",
        json=body,
        headers={
            "X-EIP712-Signature": sig.hex(),
            "X-EIP712-Signer": acct.address,
        },
    )

    assert resp.status_code == 409
    assert "rotation" in resp.text.lower()

    # Verify no third freeze row was inserted
    conn = sqlite3.connect(str(rot_db))
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        "SELECT COUNT(*) as c FROM adjudication_decision "
        "WHERE agent_did = ? AND decision_type = 'freeze'",
        ("did:adj:agent3",),
    ).fetchone()
    conn.close()
    assert row["c"] == 0


# ---------------------------------------------------------------------------
# RW2 — Different adjudicator's intervening freeze resets the streak
# ---------------------------------------------------------------------------


def test_rw2_intervening_adjudicator_resets_streak(
    rot_db: Path,
    rot_client: TestClient,
) -> None:
    """Adj1, Adj1, Adj2; POST /freeze by Adj1 → HTTP 200, row inserted."""
    acct1 = Account.create()
    acct2 = Account.create()

    _seed_adjudicators(
        rot_db,
        [
            {"adjudicator_did": "did:adj:adj1", "eth_address": acct1.address},
            {"adjudicator_did": "did:adj:adj2", "eth_address": acct2.address},
        ],
    )
    _seed_agents(
        rot_db,
        [
            {"agent_did": "did:adj:agent1"},
            {"agent_did": "did:adj:agent2"},
            {"agent_did": "did:adj:agent3"},
            {"agent_did": "did:adj:agent4"},
        ],
    )

    # Seed: Adj1 freeze, Adj1 freeze, Adj2 freeze (oldest first)
    _seed_decisions(
        rot_db,
        [
            ("freeze", "did:adj:adj1", "did:adj:agent1"),
            ("freeze", "did:adj:adj1", "did:adj:agent2"),
            ("freeze", "did:adj:adj2", "did:adj:agent3"),
        ],
    )

    body = {
        "target_did": "did:adj:agent4",
        "amount_wei": 0,
        "reason": "test freeze rw2",
        "nonce": 1,
    }
    sig = sign(acct1.key, DOMAIN, "Sanction", body)

    resp = rot_client.post(
        "/api/adjudication/freeze",
        json=body,
        headers={
            "X-EIP712-Signature": sig.hex(),
            "X-EIP712-Signer": acct1.address,
        },
    )

    assert resp.status_code == 200
    data = resp.json()
    assert data["decision_type"] == "freeze"

    # Verify row has issued_by_did = did(Adj1)
    conn = sqlite3.connect(str(rot_db))
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        "SELECT issued_by_did FROM adjudication_decision "
        "WHERE agent_did = ? AND decision_type = 'freeze'",
        ("did:adj:agent4",),
    ).fetchone()
    conn.close()
    assert row is not None
    assert row["issued_by_did"] == "did:adj:adj1"


# ---------------------------------------------------------------------------
# RW3 — Slash streak does not pollute freeze streak
# ---------------------------------------------------------------------------


def test_rw3_slash_streak_does_not_pollute_freeze_streak(
    rot_db: Path,
    rot_client: TestClient,
) -> None:
    """Adj1 issued 2 slashes; POST /freeze by Adj1 → HTTP 200, freeze row written."""
    acct = Account.create()

    _seed_adjudicators(
        rot_db,
        [{"adjudicator_did": "did:adj:adj1", "eth_address": acct.address}],
    )
    _seed_agents(
        rot_db,
        [
            {"agent_did": "did:adj:agent1"},
            {"agent_did": "did:adj:agent2"},
            {"agent_did": "did:adj:agent3"},
        ],
    )

    # Seed 2 slashes by Adj1 (different decision_type)
    _seed_decisions(
        rot_db,
        [
            ("slash", "did:adj:adj1", "did:adj:agent1"),
            ("slash", "did:adj:adj1", "did:adj:agent2"),
        ],
    )

    body = {
        "target_did": "did:adj:agent3",
        "amount_wei": 0,
        "reason": "test freeze rw3",
        "nonce": 1,
    }
    sig = sign(acct.key, DOMAIN, "Sanction", body)

    resp = rot_client.post(
        "/api/adjudication/freeze",
        json=body,
        headers={
            "X-EIP712-Signature": sig.hex(),
            "X-EIP712-Signer": acct.address,
        },
    )

    assert resp.status_code == 200
    data = resp.json()
    assert data["decision_type"] == "freeze"

    # Verify freeze row was written
    conn = sqlite3.connect(str(rot_db))
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        "SELECT COUNT(*) as c FROM adjudication_decision "
        "WHERE agent_did = ? AND decision_type = 'freeze'",
        ("did:adj:agent3",),
    ).fetchone()
    conn.close()
    assert row["c"] == 1


# ---------------------------------------------------------------------------
# RW4 — Service-level RotationViolationError
# ---------------------------------------------------------------------------


def test_rw4_service_level_rotation_violation(rot_db: Path) -> None:
    """Direct call to freeze_agent with 2 prior consecutive freezes raises."""
    from oasis.adjudication.sanctions import SanctionEngine
    from oasis.config import PlatformConfig

    # Lazy import so the test fails gracefully during the Red phase if the
    # exception has not yet been defined.
    try:
        from oasis.adjudication.rotation import RotationViolationError
    except ImportError:
        pytest.fail(
            "RotationViolationError not yet defined in oasis.adjudication.rotation"
        )

    _seed_agents(
        rot_db,
        [
            {"agent_did": "did:adj:agent1"},
            {"agent_did": "did:adj:agent2"},
            {"agent_did": "did:adj:agent3"},
        ],
    )

    # Seed 2 consecutive freezes by Adj1
    _seed_decisions(
        rot_db,
        [
            ("freeze", "did:adj:adj1", "did:adj:agent1"),
            ("freeze", "did:adj:adj1", "did:adj:agent2"),
        ],
    )

    engine = SanctionEngine(PlatformConfig())

    with pytest.raises(RotationViolationError):
        engine.freeze_agent(
            agent_did="did:adj:agent3",
            reason="test freeze rw4",
            db_path=rot_db,
            issued_by_did="did:adj:adj1",
        )


# ---------------------------------------------------------------------------
# RW5 — Service-level RotationViolationError for slash_stake
# ---------------------------------------------------------------------------


def test_rw5_slash_stake_rotation_violation(rot_db: Path) -> None:
    """Direct call to slash_stake with 2 prior consecutive slashes raises."""
    from oasis.adjudication.sanctions import SanctionEngine
    from oasis.config import PlatformConfig
    from oasis.adjudication.rotation import RotationViolationError

    _seed_agents(
        rot_db,
        [
            {"agent_did": "did:adj:agent1"},
            {"agent_did": "did:adj:agent2"},
            {"agent_did": "did:adj:agent3"},
        ],
    )

    # Seed 2 consecutive slashes by Adj1
    _seed_decisions(
        rot_db,
        [
            ("slash", "did:adj:adj1", "did:adj:agent1"),
            ("slash", "did:adj:adj1", "did:adj:agent2"),
        ],
    )

    engine = SanctionEngine(PlatformConfig())

    with pytest.raises(RotationViolationError):
        engine.slash_stake(
            agent_did="did:adj:agent3",
            amount=10.0,
            reason="test slash rw5",
            db_path=rot_db,
            issued_by_did="did:adj:adj1",
        )


# ---------------------------------------------------------------------------
# RW6 — Service-level RotationViolationError for record_override
# ---------------------------------------------------------------------------


def test_rw6_record_override_rotation_violation(rot_db: Path) -> None:
    """Direct call to record_override with 2 prior consecutive overrides raises."""
    from oasis.adjudication.sanctions import SanctionEngine
    from oasis.config import PlatformConfig
    from oasis.adjudication.rotation import RotationViolationError

    _seed_agents(
        rot_db,
        [
            {"agent_did": "did:adj:agent1"},
            {"agent_did": "did:adj:agent2"},
            {"agent_did": "did:adj:agent3"},
        ],
    )

    # Seed 2 consecutive overrides by Adj1
    _seed_decisions(
        rot_db,
        [
            ("override", "did:adj:adj1", "did:adj:agent1"),
            ("override", "did:adj:adj1", "did:adj:agent2"),
        ],
    )

    engine = SanctionEngine(PlatformConfig())

    with pytest.raises(RotationViolationError):
        engine.record_override(
            agent_did="did:adj:agent3",
            reason="test override rw6",
            db_path=rot_db,
            issued_by_did="did:adj:adj1",
        )


# ---------------------------------------------------------------------------
# RW7 — Service-level RotationViolationError for unfreeze_agent
# ---------------------------------------------------------------------------


def test_rw7_unfreeze_agent_rotation_violation(rot_db: Path) -> None:
    """Direct call to unfreeze_agent with 2 prior consecutive unfreezes raises."""
    from oasis.adjudication.sanctions import SanctionEngine
    from oasis.config import PlatformConfig
    from oasis.adjudication.rotation import RotationViolationError

    _seed_agents(
        rot_db,
        [
            {"agent_did": "did:adj:agent1"},
            {"agent_did": "did:adj:agent2"},
            {"agent_did": "did:adj:agent3"},
        ],
    )

    # Seed 2 consecutive unfreezes by Adj1
    _seed_decisions(
        rot_db,
        [
            ("unfreeze", "did:adj:adj1", "did:adj:agent1"),
            ("unfreeze", "did:adj:adj1", "did:adj:agent2"),
        ],
    )

    engine = SanctionEngine(PlatformConfig())

    with pytest.raises(RotationViolationError):
        engine.unfreeze_agent(
            agent_did="did:adj:agent3",
            db_path=rot_db,
            issued_by_did="did:adj:adj1",
        )
