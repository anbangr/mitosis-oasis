"""P6 — Test Speaker voting methods."""
import json
import sqlite3
from pathlib import Path

from oasis.governance.clerks.speaker import Speaker


def _setup(governance_db: Path) -> Speaker:
    """Create speaker with session and proposals."""
    sp = Speaker(str(governance_db), "did:oasis:clerk-speaker")
    conn = sqlite3.connect(str(governance_db))
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute(
        "INSERT OR IGNORE INTO legislative_session "
        "(session_id, state, epoch) VALUES ('sess-vote', 'BIDDING_OPEN', 0)"
    )
    # Register 3 producers
    for i in range(1, 4):
        conn.execute(
            "INSERT OR IGNORE INTO agent_registry "
            "(agent_did, agent_type, display_name, human_principal, reputation_score) "
            "VALUES (?, 'producer', ?, 'test@example.com', 0.5)",
            (f"did:mock:voter-{i}", f"Voter {i}"),
        )
    # Insert proposals
    conn.execute(
        "INSERT INTO proposal (proposal_id, session_id, proposer_did, dag_spec, "
        "token_budget_total, deadline_ms, status) VALUES (?, ?, ?, '{}', 100, 60000, 'submitted')",
        ("prop-X", "sess-vote", "did:mock:voter-1"),
    )
    conn.execute(
        "INSERT INTO proposal (proposal_id, session_id, proposer_did, dag_spec, "
        "token_budget_total, deadline_ms, status) VALUES (?, ?, ?, '{}', 100, 60000, 'submitted')",
        ("prop-Y", "sess-vote", "did:mock:voter-1"),
    )
    conn.commit()
    conn.close()
    return sp


def test_copeland_tabulation(governance_db: Path):
    """tabulate_votes produces a Copeland winner."""
    sp = _setup(governance_db)
    ballots = {
        "did:mock:voter-1": ["prop-X", "prop-Y"],
        "did:mock:voter-2": ["prop-X", "prop-Y"],
        "did:mock:voter-3": ["prop-Y", "prop-X"],
    }
    result = sp.tabulate_votes("sess-vote", ballots)
    assert result["winner"] == "prop-X"
    assert result["scores"]["prop-X"] > result["scores"]["prop-Y"]


def test_quorum_check(governance_db: Path):
    """tabulate_votes reports quorum status."""
    sp = _setup(governance_db)
    # 2 of 3 voters (67% > 51%)
    ballots = {
        "did:mock:voter-1": ["prop-X", "prop-Y"],
        "did:mock:voter-2": ["prop-X", "prop-Y"],
    }
    result = sp.tabulate_votes("sess-vote", ballots)
    assert result["quorum_met"] is True


def test_coordination_detection(governance_db: Path):
    """check_coordination returns a report with flagged and avg_tau."""
    sp = _setup(governance_db)

    conn = sqlite3.connect(str(governance_db))
    conn.execute("PRAGMA foreign_keys = ON")
    # Insert straw poll data
    for i in range(1, 4):
        conn.execute(
            "INSERT INTO straw_poll "
            "(session_id, agent_did, proposal_id, preference_ranking) "
            "VALUES ('sess-vote', ?, 'prop-X', ?)",
            (f"did:mock:voter-{i}", json.dumps(["prop-X", "prop-Y"])),
        )
    # Insert final votes (same order = high correlation)
    for i in range(1, 4):
        conn.execute(
            "INSERT INTO vote "
            "(session_id, agent_did, preference_ranking) "
            "VALUES ('sess-vote', ?, ?)",
            (f"did:mock:voter-{i}", json.dumps(["prop-X", "prop-Y"])),
        )
    conn.commit()
    conn.close()

    report = sp.check_coordination("sess-vote")
    assert "flagged" in report
    assert "avg_tau" in report
    # Same rankings → tau = 1.0 → flagged
    assert report["avg_tau"] == 1.0
    assert report["flagged"] is True


def test_result_stored(governance_db: Path):
    """tabulate_votes stores votes in the vote table."""
    sp = _setup(governance_db)
    ballots = {
        "did:mock:voter-1": ["prop-X", "prop-Y"],
        "did:mock:voter-2": ["prop-Y", "prop-X"],
    }
    sp.tabulate_votes("sess-vote", ballots)

    conn = sqlite3.connect(str(governance_db))
    count = conn.execute(
        "SELECT COUNT(*) FROM vote WHERE session_id = 'sess-vote'"
    ).fetchone()[0]
    conn.close()
    assert count == 2
