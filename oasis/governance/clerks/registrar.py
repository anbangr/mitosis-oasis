"""Registrar clerk — identity verification and quorum management.

Handles:
- Opening legislative sessions (MSG1)
- Verifying agent identity attestations (MSG2)
- Checking quorum (required roles present)
- Admitting agents to sessions
- Layer 2: Sybil pattern detection (burst registrations, similar profiles)
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from difflib import SequenceMatcher
from typing import Any, Optional

from oasis.governance.clerks.base import BaseClerk
from oasis.governance.clerks.llm_interface import LLMError
from oasis.governance.messages import (
    IdentityAttestation,
    IdentityVerificationRequest,
    log_message,
)


def derive_capability_tier(profile: dict[str, Any] | None) -> str:
    """Derive the storage label for capability_tier from a capability profile.

    Maps paper-level preset names to the t1/t3/t5 schema label.
    Falls back to 't1' for unknown profiles.

    Args:
        profile: Capability profile dict. May contain 'reference_preset'
                 or be one of the known preset names directly.

    Returns:
        One of: 't1' (lightweight), 't3' (worker), 't5' (autonomous).
    """
    if not profile:
        return "t1"

    preset = profile.get("reference_preset") or profile.get("preset_name", "")
    preset = preset.lower().replace("governance_", "")

    if preset in ("lightweight", "minimal", "t1"):
        return "t1"
    if preset in ("worker", "standard", "t3"):
        return "t3"
    if preset in ("autonomous", "full", "t5"):
        return "t5"
    return "t1"


class Registrar(BaseClerk):
    """Registrar clerk — Layer 1 identity + Layer 2 Sybil detection."""

    # Default burst detection parameters
    BURST_WINDOW_SECONDS = 60  # registrations within this window trigger flag
    BURST_THRESHOLD = 5  # number of registrations that constitutes a burst
    SIMILARITY_THRESHOLD = 0.7  # profile name similarity threshold

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
    # Agent Registration
    # ------------------------------------------------------------------

    def register_agent(
        self,
        agent_did: str,
        agent_type: str,
        display_name: str,
        human_principal: str = "",
        profile: dict[str, Any] | None = None,
    ) -> None:
        """Register a new agent in the global agent_registry.
        
        Derives the correct capability tier from the provided capability profile.
        """
        tier = derive_capability_tier(profile)
        
        conn = self._connect()
        try:
            conn.execute(
                "INSERT OR IGNORE INTO agent_registry "
                "(agent_did, agent_type, capability_tier, display_name, human_principal) "
                "VALUES (?, ?, ?, ?, ?)",
                (agent_did, agent_type, tier, display_name, human_principal),
            )
            conn.commit()
        finally:
            conn.close()

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

    # ------------------------------------------------------------------
    # Layer 2: Sybil pattern detection
    # ------------------------------------------------------------------

    def layer2_reason(self, context: dict) -> Optional[dict]:
        """Detect Sybil patterns: burst registrations and similar profiles.

        Context keys:
            session_id: current session
            agent_did: agent under scrutiny
            recent_registrations: list[dict] with keys (agent_did, timestamp, display_name)
                If not provided, fetched from DB.
            burst_threshold: override for BURST_THRESHOLD
            burst_window_seconds: override for BURST_WINDOW_SECONDS

        Returns:
            dict with {flagged, reason, confidence} or None if LLM disabled.
        """
        if not self.llm_enabled or self.llm is None:
            return None

        session_id = context.get("session_id", "")
        agent_did = context.get("agent_did", "")
        registrations = context.get("recent_registrations", [])
        burst_threshold = context.get("burst_threshold", self.BURST_THRESHOLD)
        burst_window = context.get("burst_window_seconds", self.BURST_WINDOW_SECONDS)

        # If no registrations provided, fetch from DB
        if not registrations:
            registrations = self._fetch_recent_registrations(session_id)

        flags: list[str] = []
        confidence = 0.0

        # --- Heuristic 1: Burst detection ---
        burst_count = self._check_burst(registrations, burst_window)
        if burst_count >= burst_threshold:
            flags.append(
                f"Burst registration: {burst_count} agents within "
                f"{burst_window}s window (threshold: {burst_threshold})"
            )
            confidence = max(confidence, min(burst_count / (burst_threshold * 2), 0.9))

        # --- Heuristic 2: Similar profile names ---
        similar_pairs = self._check_profile_similarity(registrations, agent_did)
        if similar_pairs:
            names = ", ".join(p[0] for p in similar_pairs[:3])
            flags.append(f"Similar profile names detected: {names}")
            confidence = max(confidence, 0.6)

        # --- LLM enrichment (if heuristics flagged something) ---
        if flags:
            try:
                prompt = (
                    f"Sybil detection analysis for agent {agent_did} in session {session_id}.\n"
                    f"Heuristic flags:\n" + "\n".join(f"- {f}" for f in flags) + "\n"
                    f"Recent registrations: {len(registrations)} agents.\n"
                    f"Assess whether this pattern indicates Sybil behavior."
                )
                llm_response = self.llm.query(prompt, context)
                reason = f"Heuristic + LLM: {'; '.join(flags)}. LLM assessment: {llm_response}"
            except LLMError:
                reason = f"Heuristic only (LLM unavailable): {'; '.join(flags)}"
        else:
            reason = "No Sybil patterns detected."

        return {
            "flagged": len(flags) > 0,
            "reason": reason,
            "confidence": round(confidence, 2),
        }

    def _fetch_recent_registrations(self, session_id: str) -> list[dict]:
        """Fetch recent attestations from message_log for this session."""
        conn = self._connect()
        try:
            rows = conn.execute(
                "SELECT sender_did, created_at, payload FROM message_log "
                "WHERE session_id = ? AND msg_type = 'IDENTITY_ATTESTATION' "
                "ORDER BY created_at ASC",
                (session_id,),
            ).fetchall()
            results = []
            for r in rows:
                payload = json.loads(r["payload"]) if r["payload"] else {}
                results.append({
                    "agent_did": r["sender_did"],
                    "timestamp": r["created_at"],
                    "display_name": payload.get("display_name", r["sender_did"]),
                })
            return results
        finally:
            conn.close()

    @staticmethod
    def _check_burst(registrations: list[dict], window_seconds: int) -> int:
        """Count max registrations within a sliding window."""
        if len(registrations) < 2:
            return len(registrations)

        timestamps = []
        for reg in registrations:
            ts = reg.get("timestamp", "")
            if isinstance(ts, str) and ts:
                try:
                    dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                    timestamps.append(dt)
                except (ValueError, TypeError):
                    continue
            elif isinstance(ts, (int, float)):
                timestamps.append(datetime.fromtimestamp(ts, tz=timezone.utc))

        if not timestamps:
            # Fall back to count-based detection
            return len(registrations)

        timestamps.sort()
        max_in_window = 0
        for i, t in enumerate(timestamps):
            count = 0
            for j in range(i, len(timestamps)):
                diff = (timestamps[j] - t).total_seconds()
                if diff <= window_seconds:
                    count += 1
                else:
                    break
            max_in_window = max(max_in_window, count)

        return max_in_window

    @staticmethod
    def _check_profile_similarity(
        registrations: list[dict], target_did: str
    ) -> list[tuple[str, float]]:
        """Find profiles with suspiciously similar display names."""
        target_name = ""
        names: dict[str, str] = {}
        for reg in registrations:
            did = reg.get("agent_did", "")
            name = reg.get("display_name", did)
            if did == target_did:
                target_name = name
            names[did] = name

        if not target_name:
            return []

        similar: list[tuple[str, float]] = []
        for did, name in names.items():
            if did == target_did:
                continue
            ratio = SequenceMatcher(None, target_name.lower(), name.lower()).ratio()
            if ratio >= Registrar.SIMILARITY_THRESHOLD:
                similar.append((name, ratio))

        similar.sort(key=lambda x: -x[1])
        return similar
