"""Shared message-signature verification helper for all clerks.

Every clerk (Registrar, Speaker, Regulator, Codifier) uses
``verify_message_signature`` to verify Ed25519 signatures on incoming
protocol messages.  The helper re-derives canonical bytes from the
Pydantic model so callers never compute them separately.
"""

from __future__ import annotations

import sqlite3

from oasis.crypto import ed25519
from oasis.governance.messages import (
    ProtocolMessage,
    canonical_signed_bytes,
)


def verify_message_signature(
    *,
    msg: ProtocolMessage,
    sender_did: str,
    conn: sqlite3.Connection,
    sig_field_name: str = "signature",
) -> tuple[bool, list[str]]:
    """Verify that *msg* carries a valid Ed25519 signature from *sender_did*.

    Steps:
        1. Fetch the sender's ``public_key`` from ``agent_registry``.
        2. Re-derive ``canonical_signed_bytes(msg)``.
        3. Read the signature hex from ``getattr(msg, sig_field_name)``.
        4. Call ``ed25519.verify``.

    Returns:
        ``(True, [])`` on success, ``(False, [error, ...])`` on failure.
    """
    row = conn.execute(
        "SELECT public_key FROM agent_registry WHERE agent_did = ?",
        (sender_did,),
    ).fetchone()

    if row is None or row["public_key"] is None:
        return False, [f"No registered public_key for {sender_did}"]

    pubkey = bytes.fromhex(row["public_key"])
    canonical = canonical_signed_bytes(msg)
    sig_hex = getattr(msg, sig_field_name, None)

    if sig_hex is None:
        return False, [f"Message missing signature field {sig_field_name!r}"]

    try:
        sig = bytes.fromhex(sig_hex)
    except ValueError:
        return False, ["signature is not valid hex"]

    if not ed25519.verify(pubkey, canonical, sig):
        return False, ["Ed25519 signature verification failed"]

    return True, []
