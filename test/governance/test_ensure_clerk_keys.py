"""T5–T7, T18–T19 — ensure_clerk_keys bootstrap (Feature 8).

Imports ``ensure_clerk_keys`` from the not-yet-implemented module
``oasis.governance.clerks.bootstrap``.  Tests will fail at import time during
the Red phase.
"""

from __future__ import annotations

import os
import sqlite3
import stat
from pathlib import Path

import pytest

from oasis.crypto.did import resolve as did_resolve
from oasis.governance.schema import create_governance_tables, seed_clerks

_CLERK_ROLES = ["registrar", "speaker", "regulator", "codifier"]


@pytest.fixture(scope="module")
def ensure_clerk_keys():
    """Lazy import so collection succeeds during Red phase."""
    from oasis.governance.clerks.bootstrap import ensure_clerk_keys as fn

    return fn


def _connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA foreign_keys = ON")
    conn.row_factory = sqlite3.Row
    return conn


# ---------------------------------------------------------------------------
# T5 — ensure_clerk_keys mints fresh keypairs
# ---------------------------------------------------------------------------


def test_t5_ensure_clerk_keys_mints_fresh_keypairs(tmp_path: Path, ensure_clerk_keys):
    """Empty keys_dir + fresh DB → 4 JSON files (mode 0o600), 4 did:key rows
    with public_key, no did:oasis:clerk-* rows remain."""
    db_path = tmp_path / "g.db"
    keys_dir = tmp_path / "clerk_keys"
    create_governance_tables(db_path)
    seed_clerks(db_path)

    ensure_clerk_keys(db_path, keys_dir)

    # Four JSON key files
    for role in _CLERK_ROLES:
        key_file = keys_dir / f"{role}.json"
        assert key_file.exists(), f"Missing key file for {role}"
        mode = key_file.stat().st_mode
        assert stat.S_IMODE(mode) == 0o600, f"{role}.json mode is {oct(mode)}"

    # Directory permissions
    assert stat.S_IMODE(keys_dir.stat().st_mode) == 0o700

    # Four did:key rows in agent_registry with public_key
    conn = _connect(db_path)
    agent_rows = conn.execute(
        "SELECT agent_did, public_key FROM agent_registry WHERE agent_type = 'clerk'"
    ).fetchall()
    clerk_rows = conn.execute(
        "SELECT agent_did, clerk_role FROM clerk_registry"
    ).fetchall()
    conn.close()

    assert len(agent_rows) == 4
    assert len(clerk_rows) == 4

    for row in agent_rows:
        assert row["agent_did"].startswith("did:key:z")
        assert row["public_key"] is not None
        assert len(bytes.fromhex(row["public_key"])) == 32

    # No did:oasis:clerk-* rows in either table
    conn = _connect(db_path)
    oasis_agent = conn.execute(
        "SELECT COUNT(*) FROM agent_registry WHERE agent_did LIKE 'did:oasis:clerk-%'"
    ).fetchone()[0]
    oasis_clerk = conn.execute(
        "SELECT COUNT(*) FROM clerk_registry WHERE agent_did LIKE 'did:oasis:clerk-%'"
    ).fetchone()[0]
    conn.close()
    assert oasis_agent == 0
    assert oasis_clerk == 0


# ---------------------------------------------------------------------------
# T6 — ensure_clerk_keys is idempotent
# ---------------------------------------------------------------------------


def test_t6_ensure_clerk_keys_is_idempotent(tmp_path: Path, ensure_clerk_keys):
    """Second call on same keys_dir → files unchanged, rows unchanged,
    same mapping returned."""
    db_path = tmp_path / "g.db"
    keys_dir = tmp_path / "clerk_keys"
    create_governance_tables(db_path)
    seed_clerks(db_path)

    result1 = ensure_clerk_keys(db_path, keys_dir)

    # Capture file mtimes / contents
    file_states = {}
    for role in _CLERK_ROLES:
        key_file = keys_dir / f"{role}.json"
        file_states[role] = (key_file.stat().st_mtime, key_file.read_text())

    # Second call
    result2 = ensure_clerk_keys(db_path, keys_dir)

    # Files unchanged
    for role in _CLERK_ROLES:
        key_file = keys_dir / f"{role}.json"
        mtime, content = file_states[role]
        assert key_file.stat().st_mtime == mtime
        assert key_file.read_text() == content

    # Mapping unchanged
    assert result1 == result2

    # Registry rows unchanged
    conn = _connect(db_path)
    conn.execute(
        "SELECT agent_did, public_key FROM agent_registry WHERE agent_type = 'clerk'"
    ).fetchall()
    conn.close()

    for role in _CLERK_ROLES:
        priv1, pub1, did1 = result1[role]
        priv2, pub2, did2 = result2[role]
        assert did1 == did2
        assert pub1 == pub2
        assert priv1 == priv2


# ---------------------------------------------------------------------------
# T7 — did:key clerks satisfy Feature-7 invariant
# ---------------------------------------------------------------------------


def test_t7_did_key_clerks_satisfy_invariant(tmp_path: Path, ensure_clerk_keys):
    """For each clerk role: did starts with did:key:z and resolve(did) == pubkey."""
    db_path = tmp_path / "g.db"
    keys_dir = tmp_path / "clerk_keys"
    create_governance_tables(db_path)
    seed_clerks(db_path)

    ensure_clerk_keys(db_path, keys_dir)

    conn = _connect(db_path)
    for role in _CLERK_ROLES:
        row = conn.execute(
            "SELECT agent_did, public_key FROM agent_registry "
            "WHERE agent_did IN (SELECT agent_did FROM clerk_registry WHERE clerk_role = ?)",
            (role,),
        ).fetchone()
        assert row is not None
        did = row["agent_did"]
        pubkey_hex = row["public_key"]
        assert did.startswith("did:key:z")
        assert did_resolve(did) == bytes.fromhex(pubkey_hex)
    conn.close()


# ---------------------------------------------------------------------------
# T18 — lifespan key persistence
# ---------------------------------------------------------------------------


def test_t18_lifespan_key_persistence(tmp_path: Path, ensure_clerk_keys):
    """Two startups on same OASIS_CLERK_KEYS_DIR → stable keys, no overwrite."""
    db_path = tmp_path / "g.db"
    keys_dir = tmp_path / "clerk_keys"
    os.environ["OASIS_CLERK_KEYS_DIR"] = str(keys_dir)

    create_governance_tables(db_path)
    seed_clerks(db_path)

    # Simulate what lifespan will do: call ensure_clerk_keys on startup
    ensure_clerk_keys(db_path, keys_dir)

    # Capture first-run state
    conn = _connect(db_path)
    first_run = {
        row["clerk_role"]: {
            "agent_did": row["agent_did"],
            "public_key": row["public_key"],
        }
        for row in conn.execute(
            "SELECT cr.clerk_role, ar.agent_did, ar.public_key "
            "FROM clerk_registry cr JOIN agent_registry ar ON cr.agent_did = ar.agent_did"
        ).fetchall()
    }
    conn.close()

    first_files = {
        role: (keys_dir / f"{role}.json").read_text() for role in _CLERK_ROLES
    }

    # Simulate second startup
    ensure_clerk_keys(db_path, keys_dir)

    conn = _connect(db_path)
    second_run = {
        row["clerk_role"]: {
            "agent_did": row["agent_did"],
            "public_key": row["public_key"],
        }
        for row in conn.execute(
            "SELECT cr.clerk_role, ar.agent_did, ar.public_key "
            "FROM clerk_registry cr JOIN agent_registry ar ON cr.agent_did = ar.agent_did"
        ).fetchall()
    }
    conn.close()

    # DIDs and pubkeys stable across restarts
    for role in _CLERK_ROLES:
        assert first_run[role]["agent_did"] == second_run[role]["agent_did"]
        assert first_run[role]["public_key"] == second_run[role]["public_key"]
        assert (keys_dir / f"{role}.json").read_text() == first_files[role]


# ---------------------------------------------------------------------------
# T19 — no did:oasis:clerk-* anywhere
# ---------------------------------------------------------------------------


def test_t19_no_did_oasis_clerk_anywhere():
    """git grep returns zero matches for the old clerk DID format in
    production code."""
    import subprocess

    result = subprocess.run(
        [
            "git",
            "grep",
            "-E",
            r'"did:oasis:clerk-(registrar|speaker|regulator|codifier)"',
            "oasis/",
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 1, (
        f"Found old did:oasis:clerk-* strings in oasis/: {result.stdout}"
    )
    assert result.stdout == ""


# ---------------------------------------------------------------------------
# Edge case: OASIS_CLERK_KEYS_DIR env var honored
# ---------------------------------------------------------------------------


def test_ensure_clerk_keys_honors_env_var(
    tmp_path: Path, monkeypatch, ensure_clerk_keys
):
    """When OASIS_CLERK_KEYS_DIR is set, ensure_clerk_keys uses it as default."""
    db_path = tmp_path / "g.db"
    keys_dir = tmp_path / "env_clerk_keys"
    monkeypatch.setenv("OASIS_CLERK_KEYS_DIR", str(keys_dir))
    create_governance_tables(db_path)
    seed_clerks(db_path)

    # Call without explicit keys_dir — should fall back to env var
    ensure_clerk_keys(db_path)

    for role in _CLERK_ROLES:
        assert (keys_dir / f"{role}.json").exists()
