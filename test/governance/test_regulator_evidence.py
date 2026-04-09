"""P6 — Test Regulator.publish_evidence."""
import sqlite3
from pathlib import Path

from oasis.governance.clerks.regulator import Regulator


def test_evidence_briefing_generated(governance_db: Path):
    """publish_evidence returns a briefing with performance data."""
    # Insert some reputation data
    conn = sqlite3.connect(str(governance_db))
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute(
        "INSERT INTO agent_registry "
        "(agent_did, agent_type, display_name, human_principal, reputation_score) "
        "VALUES ('did:mock:prod-1', 'producer', 'P1', 'test@example.com', 0.7)"
    )
    conn.execute(
        "INSERT INTO reputation_ledger "
        "(agent_did, old_score, new_score, performance_score, reason) "
        "VALUES ('did:mock:prod-1', 0.5, 0.7, 0.8, 'good performance')"
    )
    conn.execute(
        "INSERT OR IGNORE INTO legislative_session "
        "(session_id, state, epoch) VALUES ('sess-ev', 'BIDDING_OPEN', 0)"
    )
    conn.commit()
    conn.close()

    reg = Regulator(str(governance_db), "did:oasis:clerk-regulator")
    briefing = reg.publish_evidence("sess-ev")
    assert "bidder_performance" in briefing
    assert "published_at" in briefing
    assert "did:mock:prod-1" in briefing["bidder_performance"]


def test_empty_data_handled(governance_db: Path):
    """publish_evidence works with no reputation data."""
    conn = sqlite3.connect(str(governance_db))
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute(
        "INSERT OR IGNORE INTO legislative_session "
        "(session_id, state, epoch) VALUES ('sess-ev2', 'BIDDING_OPEN', 0)"
    )
    conn.commit()
    conn.close()

    reg = Regulator(str(governance_db), "did:oasis:clerk-regulator")
    briefing = reg.publish_evidence("sess-ev2")
    assert briefing["bidder_performance"] == {}
    assert "published_at" in briefing
