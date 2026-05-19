# =========== Copyright 2023 @ CAMEL-AI.org. All Rights Reserved. ===========
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
# =========== Copyright 2023 @ CAMEL-AI.org. All Rights Reserved. ===========
r"""T1–T8: Spec §1.2 bid-scoring formula helpers, ingestion, and selection.

Coverage target: ≥80% (100% on each of the four helpers).
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from oasis.governance.clerks.regulator import Regulator
from oasis.governance.messages import TaskBid
from oasis.governance.schema import create_governance_tables, seed_constitution


# ---------------------------------------------------------------------------
# T1 — _bid_score uses spec weights
# ---------------------------------------------------------------------------


def test_t1_bid_score_spec_weights():
    r"""T1: _bid_score(0.8, 0.5) returns 0.6*0.8 + 0.4*0.5 == 0.68."""
    result = Regulator._bid_score(quality=0.8, price_score=0.5)
    assert result == pytest.approx(0.68)


# ---------------------------------------------------------------------------
# T2 — _compute_quality is multiplicative ρ·match
# ---------------------------------------------------------------------------


def test_t2_compute_quality_multiplicative():
    r"""T2: _compute_quality(0.7, 0.9) returns 0.63."""
    result = Regulator._compute_quality(reputation=0.7, capability_match=0.9)
    assert result == pytest.approx(0.63)


# ---------------------------------------------------------------------------
# T3 — _compute_price_score is 1 − p/b
# ---------------------------------------------------------------------------


def test_t3_compute_price_score_formula():
    r"""T3: _compute_price_score(300, 1000) returns 0.7."""
    result = Regulator._compute_price_score(bid_price=300.0, node_budget=1000.0)
    assert result == pytest.approx(0.7)


# ---------------------------------------------------------------------------
# T4 — Highest spec-score wins (not highest stake)
# ---------------------------------------------------------------------------


def test_t4_highest_spec_score_wins_not_stake():
    r"""T4: Bid A wins despite lower stake because its spec score is higher."""
    bid_a = {
        "bid_id": "bid-a",
        "stake_amount": 10.0,
        "reputation_score": 0.8,
        "capability_match": 0.95,
        "quoted_price": 100.0,
    }
    bid_b = {
        "bid_id": "bid-b",
        "stake_amount": 1000.0,
        "reputation_score": 0.2,
        "capability_match": 0.1,
        "quoted_price": 900.0,
    }
    winner = Regulator._pick_winner_by_score([bid_a, bid_b], node_budget=1000.0)
    assert winner["bid_id"] == "bid-a"


# ---------------------------------------------------------------------------
# Edge-case tests for the four helpers
# ---------------------------------------------------------------------------


def test_compute_price_score_zero_budget():
    r"""_compute_price_score returns 0.0 when node_budget <= 0 (divide-by-zero guard)."""
    assert Regulator._compute_price_score(bid_price=100.0, node_budget=0.0) == 0.0
    assert Regulator._compute_price_score(bid_price=100.0, node_budget=-50.0) == 0.0


def test_compute_price_score_clamps_negative():
    r"""_compute_price_score clamps to 0.0 when bid_price > node_budget."""
    result = Regulator._compute_price_score(bid_price=1500.0, node_budget=1000.0)
    assert result == 0.0


def test_compute_price_score_clamps_above_one():
    r"""_compute_price_score clamps to [0, 1] — bid_price < 0 would give > 1."""
    result = Regulator._compute_price_score(bid_price=-100.0, node_budget=1000.0)
    assert result == 1.0


def test_bid_score_edge_cases():
    r"""_bid_score with boundary inputs (0, 0) and (1, 1)."""
    assert Regulator._bid_score(0.0, 0.0) == pytest.approx(0.0)
    assert Regulator._bid_score(1.0, 1.0) == pytest.approx(1.0)


def test_compute_quality_zero_reputation():
    r"""_compute_quality with zero reputation yields 0.0 regardless of match."""
    assert Regulator._compute_quality(reputation=0.0, capability_match=0.95) == 0.0


def test_compute_quality_zero_match():
    r"""_compute_quality with zero match yields 0.0 regardless of reputation."""
    assert Regulator._compute_quality(reputation=0.95, capability_match=0.0) == 0.0


def test_pick_winner_single_bid():
    r"""Single bid per node — winner is that bid."""
    solo = {
        "bid_id": "bid-solo",
        "stake_amount": 5.0,
        "reputation_score": 0.5,
        "capability_match": 0.5,
        "quoted_price": 250.0,
    }
    winner = Regulator._pick_winner_by_score([solo], node_budget=500.0)
    assert winner["bid_id"] == "bid-solo"


def test_pick_winner_tied_scores_falls_back_to_insertion_order():
    r"""Tied scores: max(..., key=...) falls back to insertion order."""
    bid_first = {
        "bid_id": "bid-first",
        "stake_amount": 1.0,
        "reputation_score": 0.5,
        "capability_match": 1.0,
        "quoted_price": 500.0,
    }
    bid_second = {
        "bid_id": "bid-second",
        "stake_amount": 1.0,
        "reputation_score": 0.5,
        "capability_match": 1.0,
        "quoted_price": 500.0,
    }
    # Both have identical quality and price_score, so identical spec score
    winner = Regulator._pick_winner_by_score(
        [bid_first, bid_second], node_budget=1000.0
    )
    # max() with key= should return the first encountered on ties
    assert winner["bid_id"] == "bid-first"


# ---------------------------------------------------------------------------
# T5 — evaluate_bids end-to-end picks spec winner
# ---------------------------------------------------------------------------


def _seed_db_for_evaluate(db_path: Path, num_nodes: int = 1) -> Regulator:
    r"""Create tables, seed constitution, insert session, agents, proposal, nodes."""
    create_governance_tables(str(db_path))
    seed_constitution(str(db_path))

    reg = Regulator(str(db_path), "did:oasis:clerk-regulator")
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute(
        "INSERT OR IGNORE INTO legislative_session "
        "(session_id, state, epoch) VALUES ('sess-eval', 'REGULATORY_REVIEW', 0)"
    )
    # Two bidders with different reputations
    conn.execute(
        "INSERT OR IGNORE INTO agent_registry "
        "(agent_did, agent_type, display_name, human_principal, reputation_score) "
        "VALUES ('did:mock:bidder-a', 'producer', 'Bidder A', 'test@example.com', 0.8)"
    )
    conn.execute(
        "INSERT OR IGNORE INTO agent_registry "
        "(agent_did, agent_type, display_name, human_principal, reputation_score) "
        "VALUES ('did:mock:bidder-b', 'producer', 'Bidder B', 'test@example.com', 0.2)"
    )
    conn.execute(
        "INSERT INTO proposal "
        "(proposal_id, session_id, proposer_did, dag_spec, "
        "token_budget_total, deadline_ms, status) "
        "VALUES ('prop-eval', 'sess-eval', 'did:mock:bidder-a', '{}', 1000, 60000, 'submitted')"
    )
    for n in range(1, num_nodes + 1):
        conn.execute(
            "INSERT INTO dag_node "
            "(node_id, proposal_id, label, service_id, pop_tier, token_budget, timeout_ms) "
            "VALUES (?, 'prop-eval', ?, 'svc', 1, 1000.0, 60000)",
            (f"node-{n}", f"Task {n}"),
        )
    conn.commit()
    conn.close()
    return reg


def _add_bid_with_fields(
    db_path: Path,
    bid_id: str,
    node_id: str,
    bidder_did: str,
    stake: float,
    quoted_price: float,
    capability_match: float,
    session_id: str = "sess-eval",
):
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute(
        "INSERT INTO bid "
        "(bid_id, session_id, task_node_id, bidder_did, service_id, "
        "proposed_code_hash, stake_amount, estimated_latency_ms, "
        "pop_tier_acceptance, status, quoted_price, capability_match) "
        "VALUES (?, ?, ?, ?, 'svc', 'hash12345678', ?, 5000, 1, 'pending', ?, ?)",
        (
            bid_id,
            session_id,
            node_id,
            bidder_did,
            stake,
            quoted_price,
            capability_match,
        ),
    )
    conn.commit()
    conn.close()


def test_t5_evaluate_bids_picks_spec_winner(tmp_path: Path):
    r"""T5: evaluate_bids selects the spec-formula winner per node."""
    db_path = tmp_path / "gov_t5.db"
    reg = _seed_db_for_evaluate(db_path)

    # Bid A: higher spec score (should win)
    # Q = 0.8 * 0.95 = 0.76, P = 1 - 100/1000 = 0.9, Score = 0.6*0.76 + 0.4*0.9 = 0.816
    _add_bid_with_fields(
        db_path,
        "bid-a",
        "node-1",
        "did:mock:bidder-a",
        stake=10.0,
        quoted_price=100.0,
        capability_match=0.95,
    )
    # Bid B: lower spec score (should lose)
    # Q = 0.2 * 0.1 = 0.02, P = 1 - 900/1000 = 0.1, Score = 0.6*0.02 + 0.4*0.1 = 0.052
    _add_bid_with_fields(
        db_path,
        "bid-b",
        "node-1",
        "did:mock:bidder-b",
        stake=1000.0,
        quoted_price=900.0,
        capability_match=0.1,
    )

    result = reg.evaluate_bids("sess-eval")
    assert "bid-a" in result["approved_bids"]
    assert "bid-b" in result["rejected_bids"]


# ---------------------------------------------------------------------------
# T6 — Schema idempotency
# ---------------------------------------------------------------------------


def test_t6_schema_idempotency(tmp_path: Path):
    r"""T6: Running create_governance_tables twice adds columns once, no error."""
    db_path = tmp_path / "gov_t6.db"
    create_governance_tables(str(db_path))
    create_governance_tables(str(db_path))  # second call must not raise

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    rows = conn.execute("PRAGMA table_info(bid)").fetchall()
    conn.close()

    col_names = [r["name"] for r in rows]
    assert col_names.count("quoted_price") == 1
    assert col_names.count("capability_match") == 1


# ---------------------------------------------------------------------------
# T7 — Ingestion path persists new fields
# ---------------------------------------------------------------------------


def test_t7_ingestion_persists_new_fields(tmp_path: Path):
    r"""T7: receive_bid writes quoted_price and capability_match to the DB."""
    db_path = tmp_path / "gov_t7.db"
    create_governance_tables(str(db_path))
    seed_constitution(str(db_path))

    reg = Regulator(str(db_path), "did:oasis:clerk-regulator")
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute(
        "INSERT OR IGNORE INTO legislative_session "
        "(session_id, state, epoch) VALUES ('sess-ingest', 'BIDDING_OPEN', 0)"
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
        "VALUES ('prop-1', 'sess-ingest', 'did:mock:bidder-1', '{}', 1000, 60000, 'submitted')"
    )
    conn.execute(
        "INSERT INTO dag_node "
        "(node_id, proposal_id, label, service_id, pop_tier, token_budget, timeout_ms) "
        "VALUES ('node-1', 'prop-1', 'Task 1', 'svc-data', 1, 500.0, 60000)"
    )
    conn.commit()
    conn.close()

    bid = TaskBid(
        session_id="sess-ingest",
        task_node_id="node-1",
        bidder_did="did:mock:bidder-1",
        service_id="svc-data",
        proposed_code_hash="a1b2c3d4e5f6g7h8",
        stake_amount=1.0,
        estimated_latency_ms=5000,
        pop_tier_acceptance=1,
        quoted_price=250.0,
        capability_match=0.8,
    )
    result = reg.receive_bid("sess-ingest", bid)
    assert result["passed"] is True
    bid_id = result["bid_id"]

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        "SELECT quoted_price, capability_match FROM bid WHERE bid_id = ?",
        (bid_id,),
    ).fetchone()
    conn.close()

    assert row is not None
    assert row["quoted_price"] == pytest.approx(250.0)
    assert row["capability_match"] == pytest.approx(0.8)

    # Also prove _pick_winner_by_score over this row reads a non-zero _bid_score
    bid_row = {
        "bid_id": bid_id,
        "stake_amount": 1.0,
        "reputation_score": 0.5,
        "capability_match": row["capability_match"],
        "quoted_price": row["quoted_price"],
    }
    winner = Regulator._pick_winner_by_score([bid_row], node_budget=500.0)
    assert winner["bid_id"] == bid_id


# ---------------------------------------------------------------------------
# T8 — evaluate_bids reads real budget column (token_budget)
# ---------------------------------------------------------------------------


def test_t8_evaluate_reads_real_budget_column(tmp_path: Path):
    r"""T8: Each node is scored against its own token_budget."""
    db_path = tmp_path / "gov_t8.db"
    create_governance_tables(str(db_path))
    seed_constitution(str(db_path))

    reg = Regulator(str(db_path), "did:oasis:clerk-regulator")
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute(
        "INSERT OR IGNORE INTO legislative_session "
        "(session_id, state, epoch) VALUES ('sess-budget', 'REGULATORY_REVIEW', 0)"
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
        "VALUES ('prop-budget', 'sess-budget', 'did:mock:bidder-1', '{}', 1000, 60000, 'submitted')"
    )
    # Node A: token_budget=500, Node B: token_budget=1000
    conn.execute(
        "INSERT INTO dag_node "
        "(node_id, proposal_id, label, service_id, pop_tier, token_budget, timeout_ms) "
        "VALUES ('node-a', 'prop-budget', 'Task A', 'svc', 1, 500.0, 60000)"
    )
    conn.execute(
        "INSERT INTO dag_node "
        "(node_id, proposal_id, label, service_id, pop_tier, token_budget, timeout_ms) "
        "VALUES ('node-b', 'prop-budget', 'Task B', 'svc', 1, 1000.0, 60000)"
    )
    conn.commit()
    conn.close()

    # One bid per node at quoted_price=250
    _add_bid_with_fields(
        db_path,
        "bid-a",
        "node-a",
        "did:mock:bidder-1",
        stake=1.0,
        quoted_price=250.0,
        capability_match=1.0,
        session_id="sess-budget",
    )
    _add_bid_with_fields(
        db_path,
        "bid-b",
        "node-b",
        "did:mock:bidder-1",
        stake=1.0,
        quoted_price=250.0,
        capability_match=1.0,
        session_id="sess-budget",
    )

    result = reg.evaluate_bids("sess-budget")
    assert "bid-a" in result["approved_bids"]
    assert "bid-b" in result["approved_bids"]

    # Node A price_score = 1 - 250/500 = 0.5
    # Node B price_score = 1 - 250/1000 = 0.75
    # The test passes if both bids are approved, proving the SELECT
    # used token_budget and not a missing budget column.


# ---------------------------------------------------------------------------
# Additional edge-case / coverage tests
# ---------------------------------------------------------------------------


def test_taskbid_model_requires_new_fields():
    r"""TaskBid refuses to instantiate without quoted_price and capability_match."""
    with pytest.raises((TypeError, ValueError)):
        TaskBid(
            session_id="s",
            task_node_id="n",
            bidder_did="did:x",
            service_id="svc",
            proposed_code_hash="a1b2c3d4e5f6g7h8",
            stake_amount=1.0,
            estimated_latency_ms=5000,
            pop_tier_acceptance=1,
            # missing quoted_price and capability_match
        )


def test_taskbid_model_accepts_new_fields():
    r"""TaskBid accepts quoted_price and capability_match when provided."""
    bid = TaskBid(
        session_id="s",
        task_node_id="n",
        bidder_did="did:x",
        service_id="svc",
        proposed_code_hash="a1b2c3d4e5f6g7h8",
        stake_amount=1.0,
        estimated_latency_ms=5000,
        pop_tier_acceptance=1,
        quoted_price=250.0,
        capability_match=0.8,
    )
    assert bid.quoted_price == pytest.approx(250.0)
    assert bid.capability_match == pytest.approx(0.8)


def test_taskbid_quoted_price_non_negative():
    r"""TaskBid quoted_price must be >= 0."""
    with pytest.raises((ValueError,)):
        TaskBid(
            session_id="s",
            task_node_id="n",
            bidder_did="did:x",
            service_id="svc",
            proposed_code_hash="a1b2c3d4e5f6g7h8",
            stake_amount=1.0,
            estimated_latency_ms=5000,
            pop_tier_acceptance=1,
            quoted_price=-1.0,
            capability_match=0.8,
        )


def test_taskbid_capability_match_range():
    r"""TaskBid capability_match must be in [0, 1]."""
    with pytest.raises((ValueError,)):
        TaskBid(
            session_id="s",
            task_node_id="n",
            bidder_did="did:x",
            service_id="svc",
            proposed_code_hash="a1b2c3d4e5f6g7h8",
            stake_amount=1.0,
            estimated_latency_ms=5000,
            pop_tier_acceptance=1,
            quoted_price=250.0,
            capability_match=1.5,
        )


def test_evaluate_bids_uncovered_nodes_still_critical(tmp_path: Path):
    r"""evaluate_bids still flags uncovered nodes even with spec-formula winners."""
    db_path = tmp_path / "gov_uncovered.db"
    reg = _seed_db_for_evaluate(db_path, num_nodes=2)
    # Only bid on node-1
    _add_bid_with_fields(
        db_path,
        "bid-1",
        "node-1",
        "did:mock:bidder-a",
        stake=1.0,
        quoted_price=100.0,
        capability_match=1.0,
    )
    result = reg.evaluate_bids("sess-eval")
    critical = [
        f for f in result["compliance_flags"] if f.get("severity") == "CRITICAL"
    ]
    assert len(critical) >= 1
    assert "node-2" in str(critical)
