"""P6 — Test Regulator.request_reproposal."""
import sqlite3
from pathlib import Path

from oasis.governance.clerks.regulator import Regulator


def _setup(governance_db: Path) -> Regulator:
    """Create regulator with session."""
    conn = sqlite3.connect(str(governance_db))
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute(
        "INSERT OR IGNORE INTO legislative_session "
        "(session_id, state, epoch) VALUES ('sess-reprop', 'REGULATORY_REVIEW', 0)"
    )
    conn.commit()
    conn.close()
    return Regulator(str(governance_db), "did:oasis:clerk-regulator")


def test_first_reproposal_allowed(governance_db: Path):
    """First re-proposal request succeeds."""
    reg = _setup(governance_db)
    assert reg.request_reproposal("sess-reprop", "budget too high") is True


def test_second_reproposal_allowed(governance_db: Path):
    """Second re-proposal request succeeds."""
    reg = _setup(governance_db)
    reg.request_reproposal("sess-reprop", "first re-proposal")
    assert reg.request_reproposal("sess-reprop", "second re-proposal") is True


def test_third_reproposal_rejected(governance_db: Path):
    """Third re-proposal request is rejected (max 2)."""
    reg = _setup(governance_db)
    reg.request_reproposal("sess-reprop", "first")
    reg.request_reproposal("sess-reprop", "second")
    assert reg.request_reproposal("sess-reprop", "third — should fail") is False
