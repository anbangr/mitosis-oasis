"""BaseClerk — abstract base class for all clerk agents.

Provides:
- DB connection management
- Authority envelope checking
- Layer 1 (deterministic) / Layer 2 (LLM advisory, P7) interface
"""
from __future__ import annotations

import json
import sqlite3
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Optional, Union


class BaseClerk(ABC):
    """Abstract base class for Layer 1 deterministic clerk agents."""

    def __init__(
        self,
        db_path: Union[str, Path],
        clerk_did: str,
        llm_enabled: bool = False,
    ) -> None:
        self.db_path = str(db_path)
        self.clerk_did = clerk_did
        self.llm_enabled = llm_enabled
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
                "SELECT authority_envelope FROM clerk_registry "
                "WHERE agent_did = ?",
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
        """LLM advisory reasoning (deferred to P7).

        Returns None when ``llm_enabled=False``.
        """
        if not self.llm_enabled:
            return None
        # P7 placeholder — would call LLM here
        return None
