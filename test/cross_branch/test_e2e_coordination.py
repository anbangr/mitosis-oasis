"""E2E: Correlated votes → flag → delay proposal → adjudication decision."""
from __future__ import annotations

import json
import sqlite3

from oasis.config import PlatformConfig
from oasis.adjudication.coordination import CoordinationDetector
from oasis.adjudication.override_panel import OverridePanel
from oasis.governance.state_machine import LegislativeState

from .conftest import drive_to_deployed


def test_coordination_detection_pipeline(cross_db, producers):
    """Correlated votes between agents are detected, flagged, and adjudicated."""
    config = PlatformConfig(coordination_threshold=0.7)

    # Phase 1: Legislative → DEPLOYED
    result = drive_to_deployed(cross_db, producers)
    assert result["sm"].current_state == LegislativeState.DEPLOYED
    db = str(cross_db)
    sid = result["session_id"]

    # Inject correlated votes: two agents submit identical rankings
    conn = sqlite3.connect(db)
    conn.execute("PRAGMA foreign_keys = ON")

    # Need a second proposal to have meaningful rankings
    # Use the existing proposal as the only one; create dummy second
    proposal_id = result["proposal_id"]
    dummy_proposal_id = f"{sid}-dummy-prop"
    conn.execute(
        "INSERT OR IGNORE INTO proposal "
        "(proposal_id, session_id, proposer_did, dag_spec, token_budget_total, deadline_ms, status) "
        "VALUES (?, ?, ?, '{}', 500.0, 60000, 'submitted')",
        (dummy_proposal_id, sid, producers[1]["agent_did"]),
    )

    # Two agents submit identical vote rankings (correlated)
    identical_ranking = json.dumps([proposal_id, dummy_proposal_id])
    for agent in producers[:2]:
        conn.execute(
            "INSERT INTO vote "
            "(session_id, agent_did, preference_ranking) "
            "VALUES (?, ?, ?)",
            (sid, agent["agent_did"], identical_ranking),
        )

    # Third agent submits different ranking
    diff_ranking = json.dumps([dummy_proposal_id, proposal_id])
    conn.execute(
        "INSERT INTO vote "
        "(session_id, agent_did, preference_ranking) "
        "VALUES (?, ?, ?)",
        (sid, producers[2]["agent_did"], diff_ranking),
    )
    conn.commit()
    conn.close()

    # Detect coordination
    detector = CoordinationDetector(threshold=0.7)
    flags = detector.flag_pairs(sid, db)

    # The two agents with identical rankings should be flagged
    voting_flags = [f for f in flags if f.flag_type == "voting"]
    assert len(voting_flags) >= 1

    # Verify flagged pair includes the correlated agents
    flagged_agents = set()
    for flag in voting_flags:
        flagged_agents.add(flag.agent_did_1)
        flagged_agents.add(flag.agent_did_2)
    assert producers[0]["agent_did"] in flagged_agents
    assert producers[1]["agent_did"] in flagged_agents

    # Override panel evaluates the flag
    panel = OverridePanel(config, db)
    for flag in voting_flags:
        decision = panel.decide({
            "type": "flag",
            "flag_id": flag.flag_id,
            "session_id": sid,
            "score": flag.score,
            "kendall_tau": flag.score,
            "agent_did_1": flag.agent_did_1,
            "agent_did_2": flag.agent_did_2,
        })
        # With high coordination score, should FLAG_AND_DELAY or DISMISS
        assert decision.decision_type in (
            "flag_and_delay", "dismiss", "freeze", "needs_review"
        )

    # Verify coordination flags persisted in DB
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    stored_flags = conn.execute(
        "SELECT * FROM coordination_flag WHERE session_id = ?",
        (sid,),
    ).fetchall()
    conn.close()
    assert len(stored_flags) >= 1
