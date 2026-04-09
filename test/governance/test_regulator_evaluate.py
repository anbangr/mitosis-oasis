"""P6 — Test Regulator.evaluate_bids."""
import json
import sqlite3
from pathlib import Path

from oasis.governance.clerks.regulator import Regulator


def _setup(governance_db: Path, num_nodes: int = 2, num_bidders: int = 2) -> Regulator:
    """Create regulator with session, proposals, nodes, and bids."""
    reg = Regulator(str(governance_db), "did:oasis:clerk-regulator")
    conn = sqlite3.connect(str(governance_db))
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute(
        "INSERT OR IGNORE INTO legislative_session "
        "(session_id, state, epoch) VALUES ('sess-eval', 'REGULATORY_REVIEW', 0)"
    )
    for i in range(1, num_bidders + 1):
        conn.execute(
            "INSERT OR IGNORE INTO agent_registry "
            "(agent_did, agent_type, display_name, human_principal, reputation_score) "
            "VALUES (?, 'producer', ?, 'test@example.com', 0.5)",
            (f"did:mock:bidder-{i}", f"Bidder {i}"),
        )
    conn.execute(
        "INSERT INTO proposal "
        "(proposal_id, session_id, proposer_did, dag_spec, "
        "token_budget_total, deadline_ms, status) "
        "VALUES ('prop-eval', 'sess-eval', 'did:mock:bidder-1', '{}', 1000, 60000, 'submitted')"
    )
    for n in range(1, num_nodes + 1):
        conn.execute(
            "INSERT INTO dag_node "
            "(node_id, proposal_id, label, service_id, pop_tier, token_budget, timeout_ms) "
            "VALUES (?, 'prop-eval', ?, 'svc', 1, 500.0, 60000)",
            (f"node-{n}", f"Task {n}"),
        )
    conn.commit()
    conn.close()
    return reg


def _add_bid(governance_db: Path, bid_id: str, node_id: str, bidder_did: str, stake: float = 1.0):
    conn = sqlite3.connect(str(governance_db))
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute(
        "INSERT INTO bid "
        "(bid_id, session_id, task_node_id, bidder_did, service_id, "
        "proposed_code_hash, stake_amount, estimated_latency_ms, "
        "pop_tier_acceptance, status) "
        "VALUES (?, 'sess-eval', ?, ?, 'svc', 'hash12345678', ?, 5000, 1, 'pending')",
        (bid_id, node_id, bidder_did, stake),
    )
    conn.commit()
    conn.close()


def test_all_nodes_covered_passes(governance_db: Path):
    """Evaluation passes when all nodes have at least one bid."""
    reg = _setup(governance_db)
    _add_bid(governance_db, "b1", "node-1", "did:mock:bidder-1")
    _add_bid(governance_db, "b2", "node-2", "did:mock:bidder-2")

    result = reg.evaluate_bids("sess-eval")
    assert len(result["approved_bids"]) == 2
    # No CRITICAL flags since all nodes covered
    critical = [f for f in result["compliance_flags"] if f.get("severity") == "CRITICAL"]
    assert len(critical) == 0


def test_fairness_check(governance_db: Path):
    """Fairness score is computed from bid assignments."""
    reg = _setup(governance_db)
    _add_bid(governance_db, "b1", "node-1", "did:mock:bidder-1")
    _add_bid(governance_db, "b2", "node-2", "did:mock:bidder-2")

    result = reg.evaluate_bids("sess-eval")
    assert 0.0 <= result["fairness_score"] <= 1.0


def test_critical_flag_blocks(governance_db: Path):
    """Uncovered nodes produce a CRITICAL compliance flag."""
    reg = _setup(governance_db, num_nodes=3, num_bidders=2)
    # Only bid on 2 of 3 nodes
    _add_bid(governance_db, "b1", "node-1", "did:mock:bidder-1")
    _add_bid(governance_db, "b2", "node-2", "did:mock:bidder-2")
    # node-3 uncovered

    result = reg.evaluate_bids("sess-eval")
    critical = [f for f in result["compliance_flags"] if f.get("severity") == "CRITICAL"]
    assert len(critical) >= 1
    assert "node-3" in str(critical)


def test_compliance_report(governance_db: Path):
    """evaluate_bids stores a regulatory_decision in the DB."""
    reg = _setup(governance_db)
    _add_bid(governance_db, "b1", "node-1", "did:mock:bidder-1")
    _add_bid(governance_db, "b2", "node-2", "did:mock:bidder-2")

    reg.evaluate_bids("sess-eval")

    conn = sqlite3.connect(str(governance_db))
    row = conn.execute(
        "SELECT decision_id, fairness_score FROM regulatory_decision "
        "WHERE session_id = 'sess-eval'"
    ).fetchone()
    conn.close()
    assert row is not None
    assert row[1] is not None  # fairness_score stored
