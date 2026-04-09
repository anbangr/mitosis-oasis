"""P6 — Test Regulator.receive_bid."""
import sqlite3
from pathlib import Path

from oasis.governance.clerks.regulator import Regulator
from oasis.governance.messages import TaskBid


def _setup(governance_db: Path) -> Regulator:
    """Create regulator with session, proposal, and DAG nodes."""
    reg = Regulator(str(governance_db), "did:oasis:clerk-regulator")
    conn = sqlite3.connect(str(governance_db))
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute(
        "INSERT OR IGNORE INTO legislative_session "
        "(session_id, state, epoch) VALUES ('sess-bid', 'BIDDING_OPEN', 0)"
    )
    conn.execute(
        "INSERT OR IGNORE INTO agent_registry "
        "(agent_did, agent_type, display_name, human_principal, reputation_score) "
        "VALUES ('did:mock:bidder-1', 'producer', 'Bidder', 'test@example.com', 0.5)"
    )
    conn.execute(
        "INSERT INTO proposal "
        "(proposal_id, session_id, proposer_did, dag_spec, "
        "token_budget_total, deadline_ms, status) "
        "VALUES ('prop-1', 'sess-bid', 'did:mock:bidder-1', '{}', 1000, 60000, 'submitted')"
    )
    conn.execute(
        "INSERT INTO dag_node "
        "(node_id, proposal_id, label, service_id, pop_tier, token_budget, timeout_ms) "
        "VALUES ('node-1', 'prop-1', 'Task 1', 'svc-data', 2, 500.0, 60000)"
    )
    conn.commit()
    conn.close()
    return reg


def _make_bid(**overrides) -> TaskBid:
    defaults = dict(
        session_id="sess-bid",
        task_node_id="node-1",
        bidder_did="did:mock:bidder-1",
        service_id="svc-data",
        proposed_code_hash="a1b2c3d4e5f6g7h8",
        stake_amount=1.0,
        estimated_latency_ms=5000,
        pop_tier_acceptance=2,
    )
    defaults.update(overrides)
    return TaskBid(**defaults)


def test_valid_bid_accepted(governance_db: Path):
    """Bid matching all constraints is accepted."""
    reg = _setup(governance_db)
    bid = _make_bid()
    result = reg.receive_bid("sess-bid", bid)
    assert result["passed"] is True
    assert result["bid_id"] is not None


def test_low_stake_rejected(governance_db: Path):
    """Bid with stake below minimum is rejected."""
    reg = _setup(governance_db)
    bid = _make_bid(stake_amount=0.01)  # Below reputation_floor (0.1)
    result = reg.receive_bid("sess-bid", bid)
    assert result["passed"] is False
    assert any("stake" in e.lower() for e in result["errors"])


def test_wrong_pop_tier_rejected(governance_db: Path):
    """Bid with wrong PoP tier acceptance is rejected."""
    reg = _setup(governance_db)
    bid = _make_bid(pop_tier_acceptance=1)  # Node requires tier 2
    result = reg.receive_bid("sess-bid", bid)
    assert result["passed"] is False
    assert any("tier" in e.lower() for e in result["errors"])


def test_unregistered_service_rejected(governance_db: Path):
    """Bid with service_id not matching node's service is rejected."""
    reg = _setup(governance_db)
    bid = _make_bid(service_id="wrong-service")
    result = reg.receive_bid("sess-bid", bid)
    assert result["passed"] is False
    assert any("service" in e.lower() or "mismatch" in e.lower() for e in result["errors"])


def test_code_hash_mismatch(governance_db: Path):
    """Bid with too-short code hash is rejected."""
    reg = _setup(governance_db)
    bid = _make_bid(proposed_code_hash="abc")  # < 8 chars
    result = reg.receive_bid("sess-bid", bid)
    assert result["passed"] is False
    assert any("hash" in e.lower() for e in result["errors"])
