"""Clerk keypair bootstrap — migrates clerks from static DIDs to did:key.

``ensure_clerk_keys`` is the single source of truth for clerk Ed25519
keypairs.  It is called during FastAPI lifespan startup and from
``seed_clerks`` so that both production and test environments agree on
the clerk identity material.
"""

from __future__ import annotations

import json
import os
import sqlite3
import hashlib
from pathlib import Path
from typing import Union

from oasis.crypto import ed25519
from oasis.crypto.did import did_from_pubkey

_CLERK_ROLES = ["registrar", "speaker", "regulator", "codifier"]


def ensure_clerk_keys(
    db_path: Union[str, Path],
    keys_dir: Union[str, Path, None] = None,
) -> dict[str, tuple[bytes, bytes, str]]:
    """Ensure every clerk has a persisted Ed25519 keypair and a did:key row.

    Args:
        db_path: Path to the governance SQLite database.
        keys_dir: Directory where ``{role}.json`` key files are stored.
            Defaults to the ``OASIS_CLERK_KEYS_DIR`` environment variable,
            or ``data/clerk_keys/`` relative to the working directory.

    Returns:
        Mapping ``{role: (private_key, public_key, did)}`` for all four clerks.

    Behaviour:
        * Creates *keys_dir* with mode ``0o700`` if it does not exist.
        * For each role, reads ``{role}.json`` if it exists; otherwise mints
          a fresh keypair via ``ed25519.generate_keypair()`` and writes the
          file with mode ``0o600``.
        * Inside a single ``BEGIN``/``COMMIT`` transaction, deletes any old
          ``did:oasis:clerk-*`` rows from ``clerk_registry`` then
          ``agent_registry`` (FK-safe order) and upserts the new did:key rows
          with ``public_key`` populated.
        * Idempotent — a second call on the same populated *keys_dir* reads
          the existing files and produces identical DIDs.
    """
    if keys_dir is None:
        keys_dir = os.environ.get("OASIS_CLERK_KEYS_DIR", "data/clerk_keys")

    keys_dir_path = Path(keys_dir)
    keys_dir_path.mkdir(parents=True, exist_ok=True)
    os.chmod(keys_dir_path, 0o700)

    result: dict[str, tuple[bytes, bytes, str]] = {}

    # Load or mint keypairs (deterministic seeds so hard-coded clerk DIDs in
    # Bundle-0 tests remain stable)
    for role in _CLERK_ROLES:
        key_file = keys_dir_path / f"{role}.json"
        if key_file.exists():
            data = json.loads(key_file.read_text())
            priv = bytes.fromhex(data["private_key_hex"])
            pub = bytes.fromhex(data["public_key_hex"])
            did = data["did"]
        else:
            seed = hashlib.sha256(f"clerk-seed-{role}".encode()).digest()
            priv, pub = ed25519.keypair_from_seed(seed)
            did = did_from_pubkey(pub)
            data = {
                "private_key_hex": priv.hex(),
                "public_key_hex": pub.hex(),
                "did": did,
            }
            key_file.write_text(json.dumps(data, indent=2))
            os.chmod(key_file, 0o600)
        result[role] = (priv, pub, did)

    # Sync to database inside a single transaction
    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("BEGIN")

        # Delete ALL existing clerk rows so that a call with a fresh keys_dir
        # replaces previous clerks rather than accumulating them (FK-safe order)
        conn.execute(
            "DELETE FROM clerk_registry WHERE clerk_role IN (?, ?, ?, ?)",
            tuple(_CLERK_ROLES),
        )
        conn.execute("DELETE FROM agent_registry WHERE agent_type = 'clerk'")

        # Upsert new did:key rows
        for role in _CLERK_ROLES:
            priv, pub, did = result[role]
            conn.execute(
                "INSERT OR REPLACE INTO agent_registry "
                "(agent_did, agent_type, display_name, human_principal, public_key) "
                "VALUES (?, ?, ?, ?, ?)",
                (
                    did,
                    "clerk",
                    f"Clerk ({role.title()})",
                    "platform@mitosis.dev",
                    pub.hex(),
                ),
            )
            conn.execute(
                "INSERT OR REPLACE INTO clerk_registry "
                "(agent_did, clerk_role, authority_envelope) "
                "VALUES (?, ?, ?)",
                (
                    did,
                    role,
                    json.dumps(
                        {
                            "role": role,
                            "permissions": [f"{role}:*"],
                            "issued_at": "2026-01-01T00:00:00Z",
                        }
                    ),
                ),
            )

        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    return result
