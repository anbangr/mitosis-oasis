"""Bidding coordination detection tests (3 tests)."""
from __future__ import annotations

import sqlite3

import pytest

from oasis.adjudication.coordination import CoordinationDetector


class TestCoordinationBidding:
    """Detect bidding coordination via Jaccard similarity on bid targets."""

    def _setup_bids(self, db_path, session_id, agent_bids):
        """Insert bids into DB. agent_bids: list of (agent_did, [node_ids])."""
        conn = sqlite3.connect(str(db_path))
        conn.execute("PRAGMA foreign_keys = ON")

        # Use first agent as proposer for FK satisfaction
        proposer = agent_bids[0][0] if agent_bids else "unknown"

        # Ensure the session and a dummy proposal exist
        conn.execute(
            "INSERT OR IGNORE INTO legislative_session "
            "(session_id, state, epoch, mission_budget_cap) "
            "VALUES (?, 'DEPLOYED', 0, 1000.0)",
            (session_id,),
        )
        proposal_id = f"bid-prop-{session_id}"
        conn.execute(
            "INSERT OR IGNORE INTO proposal "
            "(proposal_id, session_id, proposer_did, dag_spec, token_budget_total, deadline_ms) "
            "VALUES (?, ?, ?, '{}', 1000.0, 60000)",
            (proposal_id, session_id, proposer),
        )

        for agent_did, node_ids in agent_bids:
            for node_id in node_ids:
                # Ensure DAG node exists
                conn.execute(
                    "INSERT OR IGNORE INTO dag_node "
                    "(node_id, proposal_id, label, service_id, pop_tier, token_budget, timeout_ms) "
                    "VALUES (?, ?, 'Task', 'svc', 1, 100.0, 60000)",
                    (node_id, proposal_id),
                )
                bid_id = f"bid-{agent_did[-1]}-{node_id}"
                conn.execute(
                    "INSERT OR IGNORE INTO bid "
                    "(bid_id, session_id, task_node_id, bidder_did, stake_amount, status) "
                    "VALUES (?, ?, ?, ?, 1.0, 'pending')",
                    (bid_id, session_id, node_id, agent_did),
                )

        conn.commit()
        conn.close()

    def test_overlapping_targets_flagged(self, adjudication_db, agents):
        """Two agents bidding on identical targets are flagged."""
        session_id = "coord-sess-bid-1"
        targets = ["node-A", "node-B", "node-C"]
        self._setup_bids(adjudication_db, session_id, [
            (agents[0]["agent_did"], targets),
            (agents[1]["agent_did"], targets),  # identical targets
        ])

        detector = CoordinationDetector(threshold=0.8)
        results = detector.detect_bidding_coordination(session_id, adjudication_db)
        assert len(results) >= 1
        _, _, jaccard = results[0]
        assert jaccard == 1.0

    def test_diverse_bids_not_flagged(self, adjudication_db, agents):
        """Two agents with completely different targets are not flagged."""
        session_id = "coord-sess-bid-2"
        self._setup_bids(adjudication_db, session_id, [
            (agents[0]["agent_did"], ["node-X", "node-Y"]),
            (agents[1]["agent_did"], ["node-Z", "node-W"]),
        ])

        detector = CoordinationDetector(threshold=0.8)
        results = detector.detect_bidding_coordination(session_id, adjudication_db)
        assert len(results) == 0

    def test_jaccard_computed_correctly(self, adjudication_db, agents):
        """Jaccard similarity is computed as |A∩B| / |A∪B|."""
        # Direct unit test on the static method
        assert CoordinationDetector.jaccard_similarity(
            {"a", "b", "c"}, {"b", "c", "d"}
        ) == pytest.approx(2 / 4)  # {b,c} / {a,b,c,d}

        assert CoordinationDetector.jaccard_similarity(
            {"a", "b"}, {"a", "b"}
        ) == pytest.approx(1.0)

        assert CoordinationDetector.jaccard_similarity(
            {"a"}, {"b"}
        ) == pytest.approx(0.0)

        assert CoordinationDetector.jaccard_similarity(set(), set()) == 0.0
