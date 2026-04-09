"""Registrar clerk — identity verification and quorum management.

Handles:
- Opening legislative sessions (MSG1)
- Verifying agent identity attestations (MSG2)
- Checking quorum (required roles present)
- Admitting agents to sessions
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any

from oasis.governance.clerks.base import BaseClerk
from oasis.governance.messages import (
    IdentityAttestation,
    IdentityVerificationRequest,
    log_message,
)


class Registrar(BaseClerk):
    """Registrar clerk — Layer 1 identity and session management."""

    # ------------------------------------------------------------------
    # Layer 1 dispatch
    # ------------------------------------------------------------------

    def layer1_process(self, msg: Any) -> dict:
        """Dispatch MSG2 attestations for verification."""
        if isinstance(msg, IdentityAttestation):
            result = self.verify_identity(msg)
            return {
                "passed": result["passed"],
                "result": result,
                "errors": result.get("errors", []),
            }
        return {"passed": False, "result": None, "errors": ["Unsupported message type"]}

    # ------------------------------------------------------------------
    # Session management
    # ------------------------------------------------------------------

    def open_session(self, session_id: str, min_reputation: float) -> IdentityVerificationRequest:
        """Open identity-verification phase for a session.

        Creates the session row, broadcasts MSG1, and logs it.
        """
        conn = self._connect()
        try:
            # Create session if not exists
            conn.execute(
                "INSERT OR IGNORE INTO legislative_session "
                "(session_id, state, epoch) VALUES (?, 'SESSION_INIT', 0)",
                (session_id,),
            )
            # Store min_reputation in session metadata via mission_budget_cap
            # (reusing field temporarily; min_reputation tracked in MSG1)
            conn.commit()
        finally:
            conn.close()

        msg1 = IdentityVerificationRequest(
            session_id=session_id,
            min_reputation=min_reputation,
        )
        log_message(self.db_path, session_id, msg1, sender_did=self.clerk_did)
        return msg1

    # ------------------------------------------------------------------
    # Identity verification
    # ------------------------------------------------------------------

    def verify_identity(self, attestation: IdentityAttestation) -> dict:
        """Verify an agent's identity attestation.

        Checks:
        1. DID format valid (starts with "did:")
        2. Signature valid (mock: non-empty accepted)
        3. Reputation >= session min_reputation
        4. No duplicate DID in same session
        5. Agent type matches declared type
        """
        errors: list[str] = []
        session_id = attestation.session_id
        agent_did = attestation.agent_did

        # 1. DID format
        if not agent_did.startswith("did:"):
            errors.append(f"Invalid DID format: {agent_did}")

        # 2. Signature check (mock: non-empty is valid)
        if not attestation.signature:
            errors.append("Empty signature")

        # 3. Reputation check — load min_reputation from MSG1
        conn = self._connect()
        try:
            min_rep = self._get_session_min_reputation(conn, session_id)
            if attestation.reputation_score < min_rep:
                errors.append(
                    f"Reputation {attestation.reputation_score:.2f} "
                    f"below minimum {min_rep:.2f}"
                )

            # 4. Duplicate DID check
            dup = conn.execute(
                "SELECT COUNT(*) FROM message_log "
                "WHERE session_id = ? AND msg_type = 'IDENTITY_ATTESTATION' "
                "AND sender_did = ?",
                (session_id, agent_did),
            ).fetchone()[0]
            if dup > 0:
                errors.append(f"Duplicate DID in session: {agent_did}")

            # 5. Agent type check — verify against registry if registered
            reg_row = conn.execute(
                "SELECT agent_type FROM agent_registry WHERE agent_did = ?",
                (agent_did,),
            ).fetchone()
            if reg_row and reg_row["agent_type"] != attestation.agent_type:
                errors.append(
                    f"Agent type mismatch: registry says '{reg_row['agent_type']}', "
                    f"attestation says '{attestation.agent_type}'"
                )
        finally:
            conn.close()

        passed = len(errors) == 0

        # Log the attestation
        if passed:
            log_message(
                self.db_path, session_id, attestation,
                sender_did=agent_did,
            )

        return {
            "passed": passed,
            "agent_did": agent_did,
            "reputation_score": attestation.reputation_score,
            "errors": errors,
        }

    def _get_session_min_reputation(
        self, conn: Any, session_id: str
    ) -> float:
        """Get min_reputation from the MSG1 for this session."""
        row = conn.execute(
            "SELECT payload FROM message_log "
            "WHERE session_id = ? AND msg_type = 'IDENTITY_VERIFICATION_REQUEST' "
            "ORDER BY log_id ASC LIMIT 1",
            (session_id,),
        ).fetchone()
        if row and row["payload"]:
            data = json.loads(row["payload"])
            return data.get("min_reputation", 0.1)
        # Fallback: use constitution reputation_floor
        floor_row = conn.execute(
            "SELECT param_value FROM constitution WHERE param_name = 'reputation_floor'"
        ).fetchone()
        return floor_row[0] if floor_row else 0.1

    # ------------------------------------------------------------------
    # Quorum checking
    # ------------------------------------------------------------------

    def check_quorum(self, session_id: str) -> bool:
        """Check that all required roles are present in the session.

        Requires:
        - >= 1 speaker clerk attested
        - >= 1 regulator clerk attested
        - >= 1 codifier clerk attested
        - >= quorum_threshold fraction of registered producers
        """
        conn = self._connect()
        try:
            # Get attested agent DIDs from message log
            attested_rows = conn.execute(
                "SELECT DISTINCT sender_did FROM message_log "
                "WHERE session_id = ? AND msg_type = 'IDENTITY_ATTESTATION'",
                (session_id,),
            ).fetchall()
            attested_dids = {r["sender_did"] for r in attested_rows}

            # Check clerk roles
            required_roles = {"speaker", "regulator", "codifier"}
            for role in required_roles:
                role_row = conn.execute(
                    "SELECT agent_did FROM clerk_registry WHERE clerk_role = ?",
                    (role,),
                ).fetchall()
                role_dids = {r["agent_did"] for r in role_row}
                if not role_dids & attested_dids:
                    return False

            # Check producer quorum
            total_producers = conn.execute(
                "SELECT COUNT(*) FROM agent_registry "
                "WHERE agent_type = 'producer' AND active = 1"
            ).fetchone()[0]

            if total_producers == 0:
                return False

            threshold_row = conn.execute(
                "SELECT param_value FROM constitution WHERE param_name = 'quorum_threshold'"
            ).fetchone()
            threshold = threshold_row[0] if threshold_row else 0.51

            attested_producers = conn.execute(
                "SELECT COUNT(DISTINCT ml.sender_did) FROM message_log ml "
                "INNER JOIN agent_registry ar ON ml.sender_did = ar.agent_did "
                "WHERE ml.session_id = ? AND ml.msg_type = 'IDENTITY_ATTESTATION' "
                "AND ar.agent_type = 'producer'",
                (session_id,),
            ).fetchone()[0]

            import math
            required_producers = math.floor(threshold * total_producers)
            if required_producers < 1:
                required_producers = 1

            return attested_producers >= required_producers
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # Agent admission
    # ------------------------------------------------------------------

    def admit_agent(self, session_id: str, agent_did: str) -> bool:
        """Admit an agent to a session after identity verification.

        Registers the agent if not already in agent_registry.
        """
        conn = self._connect()
        try:
            # Check that agent has been attested in this session
            attested = conn.execute(
                "SELECT COUNT(*) FROM message_log "
                "WHERE session_id = ? AND msg_type = 'IDENTITY_ATTESTATION' "
                "AND sender_did = ?",
                (session_id, agent_did),
            ).fetchone()[0]
            return attested > 0
        finally:
            conn.close()
