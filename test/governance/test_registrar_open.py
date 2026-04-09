"""P6 — Test Registrar.open_session."""
import json
import sqlite3
from pathlib import Path

from oasis.governance.clerks.registrar import Registrar
from oasis.governance.messages import MessageType


def test_session_created(governance_db: Path):
    """open_session creates a legislative_session row."""
    reg = Registrar(str(governance_db), "did:oasis:clerk-registrar")
    msg1 = reg.open_session("sess-1", min_reputation=0.3)

    conn = sqlite3.connect(str(governance_db))
    row = conn.execute(
        "SELECT session_id, state FROM legislative_session WHERE session_id = 'sess-1'"
    ).fetchone()
    conn.close()

    assert row is not None
    assert row[0] == "sess-1"


def test_msg1_broadcast(governance_db: Path):
    """open_session returns a valid MSG1 and logs it."""
    reg = Registrar(str(governance_db), "did:oasis:clerk-registrar")
    msg1 = reg.open_session("sess-2", min_reputation=0.2)

    assert msg1.msg_type == MessageType.IDENTITY_VERIFICATION_REQUEST
    assert msg1.session_id == "sess-2"

    # Check message log
    conn = sqlite3.connect(str(governance_db))
    row = conn.execute(
        "SELECT msg_type, sender_did FROM message_log WHERE session_id = 'sess-2'"
    ).fetchone()
    conn.close()

    assert row is not None
    assert row[0] == "IDENTITY_VERIFICATION_REQUEST"


def test_min_reputation_set(governance_db: Path):
    """MSG1 carries the specified min_reputation."""
    reg = Registrar(str(governance_db), "did:oasis:clerk-registrar")
    msg1 = reg.open_session("sess-3", min_reputation=0.5)

    assert msg1.min_reputation == 0.5
