"""BaseClerk — abstract base class for all clerk agents.

Provides:
- DB connection management
- Authority envelope checking
- Layer 1 (deterministic) / Layer 2 (LLM advisory) interface
"""

from __future__ import annotations

import json
import sqlite3
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Optional, Union

from oasis.governance.clerks.llm_interface import LLMInterface


class BaseClerk(ABC):
    """Abstract base class for Layer 1 deterministic clerk agents."""

    def __init__(
        self,
        db_path: Union[str, Path],
        clerk_did: str,
        llm_enabled: bool = False,
        llm: LLMInterface | None = None,
        private_key: bytes | None = None,
    ) -> None:
        self.db_path = str(db_path)
        self.clerk_did = clerk_did
        self.llm_enabled = llm_enabled
        self.llm = llm
        self._private_key = private_key
        self._authority_envelope: Optional[dict] = None

    # ------------------------------------------------------------------
    # DB helpers
    # ------------------------------------------------------------------

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.execute("PRAGMA foreign_keys = ON")
        conn.row_factory = sqlite3.Row
        return conn

    # ------------------------------------------------------------------
    # Authority envelope
    # ------------------------------------------------------------------

    def _load_authority_envelope(self) -> dict:
        """Load the authority envelope from clerk_registry."""
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT authority_envelope FROM clerk_registry WHERE agent_did = ?",
                (self.clerk_did,),
            ).fetchone()
            if row is None:
                return {}
            raw = row["authority_envelope"]
            return json.loads(raw) if isinstance(raw, str) else raw
        finally:
            conn.close()

    @property
    def authority_envelope(self) -> dict:
        if self._authority_envelope is None:
            self._authority_envelope = self._load_authority_envelope()
        return self._authority_envelope

    def _load_private_key(self) -> bytes | None:
        """Load the clerk's private key if it was not provided at construction.

        Tries, in order:
        1. The explicitly-provided ``private_key`` kwarg.
        2. A bootstrap key file whose stored DID matches ``self.clerk_did``.
        3. A bootstrap key file for the clerk's role (looked up in the DB).
        4. The in-process Ed25519 keypair cache (for keys minted via
           ``ed25519.generate_keypair()`` in the same process).
        """
        if self._private_key is not None:
            return self._private_key

        import json
        import os
        import sqlite3
        from pathlib import Path

        keys_dir = os.environ.get("OASIS_CLERK_KEYS_DIR", "data/clerk_keys")
        keys_path = Path(keys_dir)

        # 2. Key file with matching DID
        if keys_path.exists():
            for key_file in keys_path.glob("*.json"):
                try:
                    data = json.loads(key_file.read_text())
                    if data.get("did") == self.clerk_did:
                        self._private_key = bytes.fromhex(data["private_key_hex"])
                        return self._private_key
                except (ValueError, KeyError, json.JSONDecodeError):
                    continue

        # 3. Key file for the clerk's role
        try:
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT clerk_role FROM clerk_registry WHERE agent_did = ?",
                (self.clerk_did,),
            ).fetchone()
            conn.close()
            if row is not None and keys_path.exists():
                role = row["clerk_role"]
                key_file = keys_path / f"{role}.json"
                if key_file.exists():
                    data = json.loads(key_file.read_text())
                    self._private_key = bytes.fromhex(data["private_key_hex"])
                    return self._private_key
        except Exception:
            pass

        # 4. In-process cache (for test-generated keypairs)
        if self.clerk_did.startswith("did:key:"):
            try:
                from oasis.crypto.did import resolve as did_resolve
                from oasis.crypto import ed25519

                pub = did_resolve(self.clerk_did)
                cached_priv = ed25519.get_private_key(pub)
                if cached_priv is not None:
                    self._private_key = cached_priv
                    return self._private_key
            except Exception:
                pass

        return None

    def authority_check(self, action: str) -> bool:
        """Verify *action* is within this clerk's authority envelope.

        The envelope contains a ``permissions`` list of glob patterns
        like ``"registrar:*"`` or ``"speaker:open_voting"``.  The action
        must match at least one pattern.
        """
        envelope = self.authority_envelope
        permissions = envelope.get("permissions", [])
        role = envelope.get("role", "")

        for perm in permissions:
            if perm == f"{role}:*":
                # Wildcard — clerk can do anything under its role
                if action.startswith(f"{role}:"):
                    return True
            elif perm == action:
                return True

        return False

    # ------------------------------------------------------------------
    # Layer 1: Deterministic processing (abstract)
    # ------------------------------------------------------------------

    @abstractmethod
    def layer1_process(self, msg: Any) -> dict:
        """Deterministic Layer 1 processing.

        Returns ``{'passed': bool, 'result': Any, 'errors': [str]}``.
        """

    # ------------------------------------------------------------------
    # Layer 2: LLM advisory (P7 — returns None for now)
    # ------------------------------------------------------------------

    def layer2_reason(self, context: dict) -> Optional[dict]:
        """LLM advisory reasoning.

        Returns None when ``llm_enabled=False`` or no LLM is configured.
        Subclasses override this to provide clerk-specific reasoning.
        """
        if not self.llm_enabled or self.llm is None:
            return None
        return None
