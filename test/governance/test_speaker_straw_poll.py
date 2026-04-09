"""P6 — Test Speaker straw poll methods."""
import sqlite3
from pathlib import Path

from oasis.governance.clerks.speaker import Speaker
from oasis.governance.messages import DAGProposal


def _setup(governance_db: Path) -> Speaker:
    """Create speaker with session and two proposals."""
    sp = Speaker(str(governance_db), "did:oasis:clerk-speaker")
    conn = sqlite3.connect(str(governance_db))
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute(
        "INSERT OR IGNORE INTO legislative_session "
        "(session_id, state, epoch) VALUES ('sess-poll', 'PROPOSAL_OPEN', 0)"
    )
    conn.execute(
        "INSERT OR IGNORE INTO agent_registry "
        "(agent_did, agent_type, display_name, human_principal, reputation_score) "
        "VALUES ('did:mock:proposer-1', 'producer', 'P1', 'test@example.com', 0.5)"
    )
    # Insert proposals directly
    conn.execute(
        "INSERT INTO proposal (proposal_id, session_id, proposer_did, dag_spec, "
        "token_budget_total, deadline_ms, status) VALUES (?, ?, ?, '{}', 100, 60000, 'submitted')",
        ("prop-A", "sess-poll", "did:mock:proposer-1"),
    )
    conn.execute(
        "INSERT INTO proposal (proposal_id, session_id, proposer_did, dag_spec, "
        "token_budget_total, deadline_ms, status) VALUES (?, ?, ?, '{}', 100, 60000, 'submitted')",
        ("prop-B", "sess-poll", "did:mock:proposer-1"),
    )
    conn.commit()
    conn.close()
    return sp


def test_poll_opened(governance_db: Path):
    """open_straw_poll returns valid config with candidates."""
    sp = _setup(governance_db)
    config = sp.open_straw_poll("sess-poll")
    assert config["poll_id"] is not None
    assert len(config["candidates"]) == 2
    assert "started_at" in config


def test_ballots_collected(governance_db: Path):
    """collect_straw_poll accepts and stores ballots."""
    sp = _setup(governance_db)
    ballots = {
        "did:mock:voter-1": ["prop-A", "prop-B"],
        "did:mock:voter-2": ["prop-B", "prop-A"],
        "did:mock:voter-3": ["prop-A", "prop-B"],
    }

    # Register voters
    conn = sqlite3.connect(str(governance_db))
    conn.execute("PRAGMA foreign_keys = ON")
    for i in range(1, 4):
        conn.execute(
            "INSERT OR IGNORE INTO agent_registry "
            "(agent_did, agent_type, display_name, human_principal, reputation_score) "
            "VALUES (?, 'producer', ?, 'test@example.com', 0.5)",
            (f"did:mock:voter-{i}", f"Voter {i}"),
        )
    conn.commit()
    conn.close()

    summary = sp.collect_straw_poll("sess-poll", ballots)
    assert summary["total_votes"] == 3


def test_summary_generated(governance_db: Path):
    """Straw poll summary includes Copeland winner and scores."""
    sp = _setup(governance_db)

    conn = sqlite3.connect(str(governance_db))
    conn.execute("PRAGMA foreign_keys = ON")
    for i in range(1, 4):
        conn.execute(
            "INSERT OR IGNORE INTO agent_registry "
            "(agent_did, agent_type, display_name, human_principal, reputation_score) "
            "VALUES (?, 'producer', ?, 'test@example.com', 0.5)",
            (f"did:mock:voter-{i}", f"Voter {i}"),
        )
    conn.commit()
    conn.close()

    ballots = {
        "did:mock:voter-1": ["prop-A", "prop-B"],
        "did:mock:voter-2": ["prop-A", "prop-B"],
        "did:mock:voter-3": ["prop-B", "prop-A"],
    }
    summary = sp.collect_straw_poll("sess-poll", ballots)
    assert summary["copeland_winner"] == "prop-A"
    assert "prop-A" in summary["scores"]
    assert "prop-B" in summary["scores"]
