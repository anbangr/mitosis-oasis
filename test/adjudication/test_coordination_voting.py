"""Voting coordination detection tests (3 tests)."""
from __future__ import annotations

import json
import sqlite3

import pytest

from oasis.adjudication.coordination import CoordinationDetector


class TestCoordinationVoting:
    """Detect voting coordination via pairwise Kendall τ."""

    def _setup_votes(self, db_path, session_id, agent_votes):
        """Insert votes into the DB. agent_votes: list of (agent_did, [proposal_ids in rank order])."""
        conn = sqlite3.connect(str(db_path))
        conn.execute("PRAGMA foreign_keys = ON")

        # Use first agent as proposer for FK satisfaction
        proposer = agent_votes[0][0] if agent_votes else "unknown"

        # Ensure all proposals exist
        all_proposals = set()
        for _, proposals in agent_votes:
            all_proposals.update(proposals)
        for proposal_id in all_proposals:
            conn.execute(
                "INSERT OR IGNORE INTO proposal "
                "(proposal_id, session_id, proposer_did, dag_spec, token_budget_total, deadline_ms) "
                "VALUES (?, ?, ?, '{}', 100.0, 60000)",
                (proposal_id, session_id, proposer),
            )

        # Insert votes with preference_ranking as JSON array
        for agent_did, proposals in agent_votes:
            conn.execute(
                "INSERT INTO vote "
                "(session_id, agent_did, preference_ranking) "
                "VALUES (?, ?, ?)",
                (session_id, agent_did, json.dumps(proposals)),
            )

        conn.commit()
        conn.close()

    def test_correlated_pair_flagged(self, adjudication_db, agents):
        """Two agents with identical vote rankings are flagged."""
        session_id = "coord-sess-vote-1"
        conn = sqlite3.connect(str(adjudication_db))
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute(
            "INSERT INTO legislative_session (session_id, state, epoch, mission_budget_cap) "
            "VALUES (?, 'DEPLOYED', 0, 1000.0)",
            (session_id,),
        )
        conn.commit()
        conn.close()

        proposals = ["prop-A", "prop-B", "prop-C"]
        self._setup_votes(adjudication_db, session_id, [
            (agents[0]["agent_did"], proposals),  # A, B, C
            (agents[1]["agent_did"], proposals),  # A, B, C — identical
        ])

        detector = CoordinationDetector(threshold=0.8)
        results = detector.detect_voting_coordination(session_id, adjudication_db)
        assert len(results) >= 1
        a1, a2, tau = results[0]
        assert tau == 1.0  # perfectly correlated

    def test_uncorrelated_pair_not_flagged(self, adjudication_db, agents):
        """Two agents with opposite rankings are not flagged."""
        session_id = "coord-sess-vote-2"
        conn = sqlite3.connect(str(adjudication_db))
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute(
            "INSERT INTO legislative_session (session_id, state, epoch, mission_budget_cap) "
            "VALUES (?, 'DEPLOYED', 0, 1000.0)",
            (session_id,),
        )
        conn.commit()
        conn.close()

        self._setup_votes(adjudication_db, session_id, [
            (agents[0]["agent_did"], ["prop-X", "prop-Y", "prop-Z"]),
            (agents[1]["agent_did"], ["prop-Z", "prop-Y", "prop-X"]),  # reversed
        ])

        detector = CoordinationDetector(threshold=0.8)
        results = detector.detect_voting_coordination(session_id, adjudication_db)
        assert len(results) == 0

    def test_threshold_configurable(self, adjudication_db, agents):
        """With a lower threshold, more pairs get flagged."""
        session_id = "coord-sess-vote-3"
        conn = sqlite3.connect(str(adjudication_db))
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute(
            "INSERT INTO legislative_session (session_id, state, epoch, mission_budget_cap) "
            "VALUES (?, 'DEPLOYED', 0, 1000.0)",
            (session_id,),
        )
        conn.commit()
        conn.close()

        # Partially correlated: A,B,C vs A,C,B → τ = 0.333
        self._setup_votes(adjudication_db, session_id, [
            (agents[0]["agent_did"], ["prop-1", "prop-2", "prop-3"]),
            (agents[1]["agent_did"], ["prop-1", "prop-3", "prop-2"]),
        ])

        # High threshold — not flagged
        detector_high = CoordinationDetector(threshold=0.8)
        assert len(detector_high.detect_voting_coordination(session_id, adjudication_db)) == 0

        # Low threshold — flagged
        detector_low = CoordinationDetector(threshold=0.2)
        assert len(detector_low.detect_voting_coordination(session_id, adjudication_db)) >= 1
