"""Legislative state machine — 9-state, 13-transition protocol engine.

Implements the full legislative pipeline from the AgentCity paper (§3.4):

    SESSION_INIT → IDENTITY_VERIFICATION → PROPOSAL_OPEN → BIDDING_OPEN
    → REGULATORY_REVIEW → CODIFICATION → AWAITING_APPROVAL → DEPLOYED

With FAILED as a terminal state reachable from several states, and a
REGULATORY_REVIEW → PROPOSAL_OPEN re-proposal loop (max 2 per epoch).
"""
from __future__ import annotations

import json
import sqlite3
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Optional, Union


# ---------------------------------------------------------------------------
# State enum
# ---------------------------------------------------------------------------

class LegislativeState(str, Enum):
    """The 9 states of the legislative protocol."""
    SESSION_INIT = "SESSION_INIT"
    IDENTITY_VERIFICATION = "IDENTITY_VERIFICATION"
    PROPOSAL_OPEN = "PROPOSAL_OPEN"
    BIDDING_OPEN = "BIDDING_OPEN"
    REGULATORY_REVIEW = "REGULATORY_REVIEW"
    CODIFICATION = "CODIFICATION"
    AWAITING_APPROVAL = "AWAITING_APPROVAL"
    DEPLOYED = "DEPLOYED"
    FAILED = "FAILED"


# Terminal states — no outgoing transitions
TERMINAL_STATES = frozenset({LegislativeState.DEPLOYED, LegislativeState.FAILED})

# ---------------------------------------------------------------------------
# Transition table
# ---------------------------------------------------------------------------

# Map: (from_state) → set of valid target states
TRANSITIONS: dict[LegislativeState, set[LegislativeState]] = {
    LegislativeState.SESSION_INIT: {
        LegislativeState.IDENTITY_VERIFICATION,
    },
    LegislativeState.IDENTITY_VERIFICATION: {
        LegislativeState.PROPOSAL_OPEN,
        LegislativeState.FAILED,
    },
    LegislativeState.PROPOSAL_OPEN: {
        LegislativeState.BIDDING_OPEN,
        LegislativeState.FAILED,
    },
    LegislativeState.BIDDING_OPEN: {
        LegislativeState.REGULATORY_REVIEW,
        LegislativeState.FAILED,
    },
    LegislativeState.REGULATORY_REVIEW: {
        LegislativeState.CODIFICATION,
        LegislativeState.PROPOSAL_OPEN,  # re-proposal loop
        LegislativeState.FAILED,
    },
    LegislativeState.CODIFICATION: {
        LegislativeState.AWAITING_APPROVAL,
        LegislativeState.FAILED,
    },
    LegislativeState.AWAITING_APPROVAL: {
        LegislativeState.DEPLOYED,
        LegislativeState.FAILED,
    },
    # Terminal states have no outgoing transitions
    LegislativeState.DEPLOYED: set(),
    LegislativeState.FAILED: set(),
}


# ---------------------------------------------------------------------------
# Guard result
# ---------------------------------------------------------------------------

@dataclass
class GuardResult:
    """Result of evaluating a transition guard."""
    allowed: bool
    reason: str = ""


# ---------------------------------------------------------------------------
# Transition guards
# ---------------------------------------------------------------------------

def _guard_init_to_identity(session_id: str, conn: sqlite3.Connection, **ctx: Any) -> GuardResult:
    """SESSION_INIT → IDENTITY_VERIFICATION: Registrar broadcasts MSG1."""
    # Guard: at least one agent must be registered (besides clerks)
    row = conn.execute(
        "SELECT COUNT(*) AS cnt FROM agent_registry "
        "WHERE agent_type = 'producer' AND active = 1"
    ).fetchone()
    if row[0] == 0:
        return GuardResult(False, "No active producer agents registered")
    return GuardResult(True)


def _guard_identity_to_proposal(session_id: str, conn: sqlite3.Connection, **ctx: Any) -> GuardResult:
    """IDENTITY_VERIFICATION → PROPOSAL_OPEN: quorum of agents attested identity."""
    # Check that enough agents have sent IdentityVerificationResponse messages
    total = conn.execute(
        "SELECT COUNT(*) FROM agent_registry WHERE agent_type = 'producer' AND active = 1"
    ).fetchone()[0]
    if total == 0:
        return GuardResult(False, "No active producers")
    attested = conn.execute(
        "SELECT COUNT(DISTINCT sender_did) FROM message_log "
        "WHERE session_id = ? AND msg_type = 'IdentityVerificationResponse'",
        (session_id,),
    ).fetchone()[0]
    # Read quorum threshold from constitution
    threshold_row = conn.execute(
        "SELECT param_value FROM constitution WHERE param_name = 'quorum_threshold'"
    ).fetchone()
    threshold = threshold_row[0] if threshold_row else 0.51
    # Also check reputation floor
    rep_floor_row = conn.execute(
        "SELECT param_value FROM constitution WHERE param_name = 'reputation_floor'"
    ).fetchone()
    rep_floor = rep_floor_row[0] if rep_floor_row else 0.1
    # Check if any attested agent is below reputation floor
    below_floor = conn.execute(
        "SELECT COUNT(*) FROM agent_registry ar "
        "INNER JOIN message_log ml ON ar.agent_did = ml.sender_did "
        "WHERE ml.session_id = ? AND ml.msg_type = 'IdentityVerificationResponse' "
        "AND ar.reputation_score < ?",
        (session_id, rep_floor),
    ).fetchone()[0]
    if below_floor > 0:
        return GuardResult(False, f"{below_floor} agent(s) below reputation floor ({rep_floor})")
    if attested / total < threshold:
        return GuardResult(False, f"Quorum not met: {attested}/{total} < {threshold}")
    return GuardResult(True)


def _guard_identity_to_failed(session_id: str, conn: sqlite3.Connection, **ctx: Any) -> GuardResult:
    """IDENTITY_VERIFICATION → FAILED: explicit failure (timeout or rejection)."""
    reason = ctx.get("reason", "Identity verification failed")
    return GuardResult(True, reason)


def _guard_proposal_to_bidding(session_id: str, conn: sqlite3.Connection, **ctx: Any) -> GuardResult:
    """PROPOSAL_OPEN → BIDDING_OPEN: valid MSG3 (ProposalSubmission) received."""
    proposals = conn.execute(
        "SELECT COUNT(*) FROM proposal WHERE session_id = ? AND status = 'submitted'",
        (session_id,),
    ).fetchone()[0]
    if proposals == 0:
        return GuardResult(False, "No proposals submitted")
    # Check budget bounds
    cap_row = conn.execute(
        "SELECT param_value FROM constitution WHERE param_name = 'budget_cap_max'"
    ).fetchone()
    budget_max = cap_row[0] if cap_row else 1_000_000.0
    over_budget = conn.execute(
        "SELECT COUNT(*) FROM proposal WHERE session_id = ? AND token_budget_total > ?",
        (session_id, budget_max),
    ).fetchone()[0]
    if over_budget > 0:
        return GuardResult(False, f"{over_budget} proposal(s) exceed budget cap ({budget_max})")
    return GuardResult(True)


def _guard_proposal_to_failed(session_id: str, conn: sqlite3.Connection, **ctx: Any) -> GuardResult:
    """PROPOSAL_OPEN → FAILED: timeout or invalid proposal."""
    return GuardResult(True, ctx.get("reason", "Proposal phase failed"))


def _guard_bidding_to_regulatory(session_id: str, conn: sqlite3.Connection, **ctx: Any) -> GuardResult:
    """BIDDING_OPEN → REGULATORY_REVIEW: all task nodes have ≥1 valid bid."""
    # Find all dag_nodes for proposals in this session
    uncovered = conn.execute(
        "SELECT dn.node_id FROM dag_node dn "
        "INNER JOIN proposal p ON dn.proposal_id = p.proposal_id "
        "WHERE p.session_id = ? "
        "AND dn.node_id NOT IN ("
        "  SELECT DISTINCT task_node_id FROM bid "
        "  WHERE session_id = ? AND status = 'pending'"
        ")",
        (session_id, session_id),
    ).fetchall()
    if uncovered:
        node_ids = [r[0] for r in uncovered]
        return GuardResult(False, f"Uncovered task nodes: {node_ids}")
    return GuardResult(True)


def _guard_bidding_to_failed(session_id: str, conn: sqlite3.Connection, **ctx: Any) -> GuardResult:
    """BIDDING_OPEN → FAILED: uncovered nodes at timeout."""
    return GuardResult(True, ctx.get("reason", "Bidding phase failed"))


def _guard_regulatory_to_codification(session_id: str, conn: sqlite3.Connection, **ctx: Any) -> GuardResult:
    """REGULATORY_REVIEW → CODIFICATION: valid MSG5, no CRITICAL flags."""
    decisions = conn.execute(
        "SELECT compliance_flags FROM regulatory_decision WHERE session_id = ?",
        (session_id,),
    ).fetchall()
    if not decisions:
        return GuardResult(False, "No regulatory decision recorded")
    for d in decisions:
        if d[0]:
            flags = json.loads(d[0]) if isinstance(d[0], str) else d[0]
            if isinstance(flags, list):
                for f in flags:
                    severity = f.get("severity", "") if isinstance(f, dict) else ""
                    if severity == "CRITICAL":
                        return GuardResult(False, f"CRITICAL compliance flag: {f}")
    return GuardResult(True)


def _guard_regulatory_to_reproposal(session_id: str, conn: sqlite3.Connection, **ctx: Any) -> GuardResult:
    """REGULATORY_REVIEW → PROPOSAL_OPEN: re-proposal requested (max 2 per epoch)."""
    row = conn.execute(
        "SELECT epoch FROM legislative_session WHERE session_id = ?",
        (session_id,),
    ).fetchone()
    if not row:
        return GuardResult(False, "Session not found")
    # Count re-proposals: transitions FROM REGULATORY_REVIEW back to PROPOSAL_OPEN
    reproposals = conn.execute(
        "SELECT COUNT(*) FROM message_log "
        "WHERE session_id = ? AND msg_type = 'StateTransition' "
        "AND payload LIKE '%REGULATORY_REVIEW%' "
        "AND payload LIKE '%\"to_state\": \"PROPOSAL_OPEN\"%'",
        (session_id,),
    ).fetchone()[0]
    max_reproposals = 2
    if reproposals >= max_reproposals:
        return GuardResult(False, f"Max re-proposals ({max_reproposals}) reached for this epoch")
    return GuardResult(True)


def _guard_codification_to_approval(session_id: str, conn: sqlite3.Connection, **ctx: Any) -> GuardResult:
    """CODIFICATION → AWAITING_APPROVAL: valid MSG6 passes constitutional validation."""
    specs = conn.execute(
        "SELECT status FROM contract_spec WHERE session_id = ?",
        (session_id,),
    ).fetchall()
    if not specs:
        return GuardResult(False, "No contract specification created")
    # At least one spec must be in 'validated' status
    validated = [s for s in specs if s[0] == "validated"]
    if not validated:
        return GuardResult(False, "No validated contract specification")
    return GuardResult(True)


def _guard_codification_to_failed(session_id: str, conn: sqlite3.Connection, **ctx: Any) -> GuardResult:
    """CODIFICATION → FAILED: validation fails after max retries."""
    return GuardResult(True, ctx.get("reason", "Codification failed"))


def _guard_approval_to_deployed(session_id: str, conn: sqlite3.Connection, **ctx: Any) -> GuardResult:
    """AWAITING_APPROVAL → DEPLOYED: MSG7 with dual signatures (proposer + regulator)."""
    signatures = ctx.get("signatures", {})
    if not signatures.get("proposer"):
        return GuardResult(False, "Missing proposer signature")
    if not signatures.get("regulator"):
        return GuardResult(False, "Missing regulator signature")
    return GuardResult(True)


def _guard_approval_to_failed(session_id: str, conn: sqlite3.Connection, **ctx: Any) -> GuardResult:
    """AWAITING_APPROVAL → FAILED: approval timeout."""
    return GuardResult(True, ctx.get("reason", "Approval timeout"))


# Map: (from_state, to_state) → guard function
GUARDS: dict[tuple[LegislativeState, LegislativeState], Any] = {
    (LegislativeState.SESSION_INIT, LegislativeState.IDENTITY_VERIFICATION): _guard_init_to_identity,
    (LegislativeState.IDENTITY_VERIFICATION, LegislativeState.PROPOSAL_OPEN): _guard_identity_to_proposal,
    (LegislativeState.IDENTITY_VERIFICATION, LegislativeState.FAILED): _guard_identity_to_failed,
    (LegislativeState.PROPOSAL_OPEN, LegislativeState.BIDDING_OPEN): _guard_proposal_to_bidding,
    (LegislativeState.PROPOSAL_OPEN, LegislativeState.FAILED): _guard_proposal_to_failed,
    (LegislativeState.BIDDING_OPEN, LegislativeState.REGULATORY_REVIEW): _guard_bidding_to_regulatory,
    (LegislativeState.BIDDING_OPEN, LegislativeState.FAILED): _guard_bidding_to_failed,
    (LegislativeState.REGULATORY_REVIEW, LegislativeState.CODIFICATION): _guard_regulatory_to_codification,
    (LegislativeState.REGULATORY_REVIEW, LegislativeState.PROPOSAL_OPEN): _guard_regulatory_to_reproposal,
    (LegislativeState.CODIFICATION, LegislativeState.AWAITING_APPROVAL): _guard_codification_to_approval,
    (LegislativeState.CODIFICATION, LegislativeState.FAILED): _guard_codification_to_failed,
    (LegislativeState.AWAITING_APPROVAL, LegislativeState.DEPLOYED): _guard_approval_to_deployed,
    (LegislativeState.AWAITING_APPROVAL, LegislativeState.FAILED): _guard_approval_to_failed,
}


# ---------------------------------------------------------------------------
# Timeout configuration
# ---------------------------------------------------------------------------

@dataclass
class TimeoutConfig:
    """Configurable timeouts per state (milliseconds)."""
    identity_verification_ms: int = 60_000       # 1 minute
    proposal_ms: int = 300_000                    # 5 minutes
    bidding_ms: int = 300_000                     # 5 minutes
    regulatory_review_ms: int = 120_000           # 2 minutes
    codification_ms: int = 120_000                # 2 minutes
    approval_ms: int = 300_000                    # 5 minutes

    def get_timeout_for_state(self, state: LegislativeState) -> Optional[int]:
        """Return timeout in ms for a state, or None if no timeout."""
        mapping = {
            LegislativeState.IDENTITY_VERIFICATION: self.identity_verification_ms,
            LegislativeState.PROPOSAL_OPEN: self.proposal_ms,
            LegislativeState.BIDDING_OPEN: self.bidding_ms,
            LegislativeState.REGULATORY_REVIEW: self.regulatory_review_ms,
            LegislativeState.CODIFICATION: self.codification_ms,
            LegislativeState.AWAITING_APPROVAL: self.approval_ms,
        }
        return mapping.get(state)


# ---------------------------------------------------------------------------
# State machine
# ---------------------------------------------------------------------------

@dataclass
class TransitionRecord:
    """Record of a state transition."""
    from_state: LegislativeState
    to_state: LegislativeState
    timestamp: str
    context: dict


class LegislativeStateMachine:
    """9-state legislative protocol engine backed by SQLite.

    Each instance is bound to a single legislative session.
    """

    def __init__(
        self,
        session_id: str,
        db_path: Union[str, Path],
        timeout_config: Optional[TimeoutConfig] = None,
    ) -> None:
        self.session_id = session_id
        self.db_path = str(db_path)
        self.timeout_config = timeout_config or TimeoutConfig()
        self._ensure_session_exists()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.execute("PRAGMA foreign_keys = ON")
        conn.row_factory = sqlite3.Row
        return conn

    def _ensure_session_exists(self) -> None:
        """Create the session row if it doesn't exist."""
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT session_id FROM legislative_session WHERE session_id = ?",
                (self.session_id,),
            ).fetchone()
            if row is None:
                conn.execute(
                    "INSERT INTO legislative_session (session_id, state, epoch) "
                    "VALUES (?, ?, ?)",
                    (self.session_id, LegislativeState.SESSION_INIT.value, 0),
                )
                conn.commit()
        finally:
            conn.close()

    @property
    def current_state(self) -> LegislativeState:
        """Return the current state of this session."""
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT state FROM legislative_session WHERE session_id = ?",
                (self.session_id,),
            ).fetchone()
            return LegislativeState(row["state"])
        finally:
            conn.close()

    def can_transition(self, target: LegislativeState, **context: Any) -> GuardResult:
        """Check whether a transition to *target* is allowed.

        Returns a ``GuardResult`` without modifying state.
        """
        current = self.current_state
        # Check structural validity
        if target not in TRANSITIONS.get(current, set()):
            return GuardResult(False, f"No transition {current.value} → {target.value}")
        # Evaluate guard
        guard_fn = GUARDS.get((current, target))
        if guard_fn is None:
            return GuardResult(True)  # no guard = always allowed
        conn = self._connect()
        try:
            return guard_fn(self.session_id, conn, **context)
        finally:
            conn.close()

    def transition(self, target: LegislativeState, **context: Any) -> GuardResult:
        """Attempt to transition to *target*.

        On success: updates the DB, logs the transition in ``message_log``,
        and returns ``GuardResult(allowed=True)``.

        On failure: returns ``GuardResult(allowed=False, reason=...)``.
        """
        current = self.current_state
        # Structural check
        if target not in TRANSITIONS.get(current, set()):
            return GuardResult(False, f"No transition {current.value} → {target.value}")
        # Guard check
        guard_fn = GUARDS.get((current, target))
        if guard_fn is not None:
            conn = self._connect()
            try:
                result = guard_fn(self.session_id, conn, **context)
            finally:
                conn.close()
            if not result.allowed:
                return result

        # Execute transition
        conn = self._connect()
        try:
            conn.execute(
                "UPDATE legislative_session SET state = ?, "
                "updated_at = CURRENT_TIMESTAMP, epoch = epoch + 1 "
                "WHERE session_id = ?",
                (target.value, self.session_id),
            )
            # If transitioning to FAILED, store the reason
            if target == LegislativeState.FAILED:
                reason = context.get("reason", "")
                conn.execute(
                    "UPDATE legislative_session SET failed_reason = ? "
                    "WHERE session_id = ?",
                    (reason, self.session_id),
                )
            # Log the transition in message_log
            payload = json.dumps({
                "from_state": current.value,
                "to_state": target.value,
                "context": {k: str(v) for k, v in context.items()},
            })
            conn.execute(
                "INSERT INTO message_log "
                "(session_id, msg_type, sender_did, receiver, payload) "
                "VALUES (?, ?, ?, ?, ?)",
                (self.session_id, "StateTransition", "system", "session", payload),
            )
            conn.commit()
        finally:
            conn.close()

        return GuardResult(True)

    def history(self) -> list[TransitionRecord]:
        """Return ordered list of state transitions for this session."""
        conn = self._connect()
        try:
            rows = conn.execute(
                "SELECT payload, created_at FROM message_log "
                "WHERE session_id = ? AND msg_type = 'StateTransition' "
                "ORDER BY log_id",
                (self.session_id,),
            ).fetchall()
            records = []
            for row in rows:
                data = json.loads(row["payload"])
                records.append(TransitionRecord(
                    from_state=LegislativeState(data["from_state"]),
                    to_state=LegislativeState(data["to_state"]),
                    timestamp=row["created_at"],
                    context=data.get("context", {}),
                ))
            return records
        finally:
            conn.close()

    def check_timeout(self) -> Optional[LegislativeState]:
        """Check if the current state has timed out.

        Returns ``LegislativeState.FAILED`` if timed out, else ``None``.
        """
        current = self.current_state
        if current in TERMINAL_STATES:
            return None
        timeout_ms = self.timeout_config.get_timeout_for_state(current)
        if timeout_ms is None:
            return None
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT updated_at FROM legislative_session WHERE session_id = ?",
                (self.session_id,),
            ).fetchone()
            if row is None:
                return None
            # Compare elapsed time
            # updated_at is stored as CURRENT_TIMESTAMP (SQLite text format)
            import datetime
            updated = datetime.datetime.fromisoformat(row["updated_at"])
            now = datetime.datetime.now()
            elapsed_ms = (now - updated).total_seconds() * 1000
            if elapsed_ms > timeout_ms:
                return LegislativeState.FAILED
            return None
        finally:
            conn.close()
