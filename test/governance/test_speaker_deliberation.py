"""P6 — Test Speaker deliberation round methods."""
import sqlite3
from pathlib import Path

from oasis.governance.clerks.speaker import Speaker


def _setup(governance_db: Path) -> Speaker:
    """Create speaker with session and attested producers."""
    sp = Speaker(str(governance_db), "did:oasis:clerk-speaker")
    conn = sqlite3.connect(str(governance_db))
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute(
        "INSERT OR IGNORE INTO legislative_session "
        "(session_id, state, epoch) VALUES ('sess-del', 'PROPOSAL_OPEN', 0)"
    )
    # Register and attest 3 producers
    for i in range(1, 4):
        did = f"did:mock:prod-{i}"
        conn.execute(
            "INSERT OR IGNORE INTO agent_registry "
            "(agent_did, agent_type, display_name, human_principal, reputation_score) "
            "VALUES (?, 'producer', ?, 'test@example.com', 0.5)",
            (did, f"Producer {i}"),
        )
        conn.execute(
            "INSERT INTO message_log "
            "(session_id, msg_type, sender_did, receiver, payload) "
            "VALUES ('sess-del', 'IDENTITY_ATTESTATION', ?, 'session', '{}')",
            (did,),
        )
    conn.commit()
    conn.close()
    return sp


def test_3_rounds_enforced(governance_db: Path):
    """Rounds 1-3 open successfully."""
    sp = _setup(governance_db)
    for r in range(1, 4):
        config = sp.open_deliberation_round("sess-del", r)
        assert config["round_number"] == r
        assert config.get("error") is None


def test_randomized_order(governance_db: Path):
    """Speaking order contains all attested producers (may be shuffled)."""
    sp = _setup(governance_db)
    config = sp.open_deliberation_round("sess-del", 1)
    order = config["speaking_order"]
    assert len(order) == 3
    assert set(order) == {"did:mock:prod-1", "did:mock:prod-2", "did:mock:prod-3"}


def test_round_closure(governance_db: Path):
    """close_deliberation_round returns a valid summary."""
    sp = _setup(governance_db)
    conn = sqlite3.connect(str(governance_db))
    conn.execute("PRAGMA foreign_keys = ON")
    # Insert some deliberation messages
    conn.execute(
        "INSERT INTO deliberation_round "
        "(session_id, round_number, agent_did, message) "
        "VALUES ('sess-del', 1, 'did:mock:prod-1', 'I support proposal A')"
    )
    conn.execute(
        "INSERT INTO deliberation_round "
        "(session_id, round_number, agent_did, message) "
        "VALUES ('sess-del', 1, 'did:mock:prod-2', 'I prefer proposal B')"
    )
    conn.commit()
    conn.close()

    summary = sp.close_deliberation_round("sess-del", 1)
    assert summary["round_number"] == 1
    assert summary["message_count"] == 2
    assert summary["participant_count"] == 2


def test_no_4th_round(governance_db: Path):
    """Round 4 is rejected (max 3)."""
    sp = _setup(governance_db)
    config = sp.open_deliberation_round("sess-del", 4)
    assert config.get("error") is not None
    assert "exceeded" in config["error"].lower() or "3" in config["error"]
