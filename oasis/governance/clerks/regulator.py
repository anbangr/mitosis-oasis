"""Regulator clerk — fairness, bid evaluation, and re-proposal enforcement.

Handles:
- Publishing evidence briefings
- Receiving and validating bids (MSG4)
- Evaluating bid sets (MSG5)
- Fairness checking (HHI)
- Re-proposal enforcement (max 2 per epoch)
- Co-signing approvals (MSG7 half)
"""
from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone
from typing import Any

from oasis.governance.clerks.base import BaseClerk
from oasis.governance.fairness import check_fairness
from oasis.governance.messages import (
    RegulatoryDecision,
    TaskBid,
    log_message,
)


class Regulator(BaseClerk):
    """Regulator clerk — Layer 1 fairness and bid management."""

    # ------------------------------------------------------------------
    # Layer 1 dispatch
    # ------------------------------------------------------------------

    def layer1_process(self, msg: Any) -> dict:
        """Dispatch MSG4 bids for validation."""
        if isinstance(msg, TaskBid):
            result = self.receive_bid(msg.session_id, msg)
            return {
                "passed": result["passed"],
                "result": result,
                "errors": result.get("errors", []),
            }
        return {"passed": False, "result": None, "errors": ["Unsupported message type"]}

    # ------------------------------------------------------------------
    # Evidence briefing
    # ------------------------------------------------------------------

    def publish_evidence(self, session_id: str) -> dict:
        """Publish on-chain performance data before deliberation.

        Queries performance data from reputation ledger (mock: sample data).
        """
        conn = self._connect()
        try:
            # Gather agent performance from reputation ledger
            rows = conn.execute(
                "SELECT agent_did, new_score, performance_score "
                "FROM reputation_ledger ORDER BY created_at DESC"
            ).fetchall()

            bidder_performance: dict[str, dict] = {}
            for r in rows:
                did = r["agent_did"]
                if did not in bidder_performance:
                    bidder_performance[did] = {
                        "reputation_score": r["new_score"],
                        "performance_score": r["performance_score"],
                    }
        finally:
            conn.close()

        return {
            "bidder_performance": bidder_performance,
            "service_performance": {},
            "published_at": datetime.now(timezone.utc).isoformat(),
        }

    # ------------------------------------------------------------------
    # Bid validation
    # ------------------------------------------------------------------

    def receive_bid(self, session_id: str, bid: TaskBid) -> dict:
        """Validate a bid against constraints.

        Checks:
        1. Service is registered (service_id exists in dag_node)
        2. Code hash format valid (non-empty, hex-like)
        3. Stake >= min_stake (derived from constitution)
        4. PoP tier acceptance matches node tier
        """
        errors: list[str] = []

        conn = self._connect()
        try:
            # 1. Check that the task node exists and get its PoP tier
            node_row = conn.execute(
                "SELECT node_id, service_id, pop_tier FROM dag_node WHERE node_id = ?",
                (bid.task_node_id,),
            ).fetchone()
            if node_row is None:
                errors.append(f"Task node not found: {bid.task_node_id}")
            else:
                # Check service_id matches (if node has one set)
                node_service = node_row["service_id"]
                if node_service and bid.service_id != node_service:
                    errors.append(
                        f"Service mismatch: node expects '{node_service}', "
                        f"bid offers '{bid.service_id}'"
                    )

                # 4. PoP tier check
                node_tier = node_row["pop_tier"]
                if bid.pop_tier_acceptance != node_tier:
                    errors.append(
                        f"PoP tier mismatch: node requires tier {node_tier}, "
                        f"bid accepts tier {bid.pop_tier_acceptance}"
                    )

            # 2. Code hash format
            if not bid.proposed_code_hash or len(bid.proposed_code_hash) < 8:
                errors.append("Invalid code hash format (too short)")

            # 3. Stake check
            rep_floor_row = conn.execute(
                "SELECT param_value FROM constitution WHERE param_name = 'reputation_floor'"
            ).fetchone()
            min_stake = rep_floor_row[0] if rep_floor_row else 0.1
            if bid.stake_amount < min_stake:
                errors.append(
                    f"Stake {bid.stake_amount:.2f} below minimum {min_stake:.2f}"
                )
        finally:
            conn.close()

        passed = len(errors) == 0
        bid_id = f"bid-{uuid.uuid4().hex[:8]}"

        if passed:
            # Store bid
            conn = self._connect()
            try:
                conn.execute(
                    "INSERT INTO bid "
                    "(bid_id, session_id, task_node_id, bidder_did, service_id, "
                    "proposed_code_hash, stake_amount, estimated_latency_ms, "
                    "pop_tier_acceptance, status) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending')",
                    (
                        bid_id, session_id, bid.task_node_id, bid.bidder_did,
                        bid.service_id, bid.proposed_code_hash, bid.stake_amount,
                        bid.estimated_latency_ms, bid.pop_tier_acceptance,
                    ),
                )
                conn.commit()
            finally:
                conn.close()

            log_message(self.db_path, session_id, bid, sender_did=bid.bidder_did)

        return {
            "passed": passed,
            "bid_id": bid_id if passed else None,
            "errors": errors,
        }

    # ------------------------------------------------------------------
    # Bid evaluation
    # ------------------------------------------------------------------

    def evaluate_bids(self, session_id: str) -> dict:
        """Evaluate all bids for a session and produce MSG5.

        1. Select best bid per node
        2. Check fairness (HHI)
        3. Flag CRITICAL compliance issues
        4. Return approved/rejected lists
        """
        conn = self._connect()
        try:
            # Get all pending bids for this session
            bids = conn.execute(
                "SELECT bid_id, task_node_id, bidder_did, stake_amount, "
                "estimated_latency_ms, pop_tier_acceptance "
                "FROM bid WHERE session_id = ? AND status = 'pending'",
                (session_id,),
            ).fetchall()

            if not bids:
                return {
                    "approved_bids": [],
                    "rejected_bids": [],
                    "fairness_score": 1.0,
                    "compliance_flags": [],
                }

            # Get all task nodes for this session
            task_nodes = conn.execute(
                "SELECT dn.node_id FROM dag_node dn "
                "INNER JOIN proposal p ON dn.proposal_id = p.proposal_id "
                "WHERE p.session_id = ?",
                (session_id,),
            ).fetchall()
            all_node_ids = {r["node_id"] for r in task_nodes}

            # Select best bid per node (highest stake, lowest latency)
            node_bids: dict[str, list] = {}
            for b in bids:
                node_id = b["task_node_id"]
                if node_id not in node_bids:
                    node_bids[node_id] = []
                node_bids[node_id].append(dict(b))

            approved: list[str] = []
            rejected: list[str] = []
            bid_assignments: dict[str, float] = {}

            for node_id, nb in node_bids.items():
                # Sort by stake descending, latency ascending
                nb.sort(key=lambda x: (-x["stake_amount"], x["estimated_latency_ms"]))
                winner = nb[0]
                approved.append(winner["bid_id"])
                bidder = winner["bidder_did"]
                bid_assignments[bidder] = bid_assignments.get(bidder, 0) + 1

                # Reject the rest
                for loser in nb[1:]:
                    rejected.append(loser["bid_id"])

            # Check coverage — all nodes must have a bid
            covered_nodes = set(node_bids.keys())
            uncovered = all_node_ids - covered_nodes
            compliance_flags: list[dict] = []
            if uncovered:
                compliance_flags.append({
                    "severity": "CRITICAL",
                    "flag": f"Uncovered task nodes: {sorted(uncovered)}",
                })

            # Normalise bid_assignments to fractions
            total_assignments = sum(bid_assignments.values())
            if total_assignments > 0:
                bid_shares = {k: v / total_assignments for k, v in bid_assignments.items()}
            else:
                bid_shares = {}

            # Fairness check
            fairness_result = check_fairness(bid_shares)
            fairness_score = fairness_result.score / 1000.0  # normalise to 0-1

            if not fairness_result.passed:
                compliance_flags.append({
                    "severity": "WARNING",
                    "flag": f"Fairness score {fairness_result.score} below threshold; "
                            f"violator: {fairness_result.violator}",
                })

            # Update bid statuses
            for bid_id in approved:
                conn.execute(
                    "UPDATE bid SET status = 'approved' WHERE bid_id = ?",
                    (bid_id,),
                )
            for bid_id in rejected:
                conn.execute(
                    "UPDATE bid SET status = 'rejected' WHERE bid_id = ?",
                    (bid_id,),
                )

            # Store regulatory decision
            decision_id = f"dec-{uuid.uuid4().hex[:8]}"
            conn.execute(
                "INSERT INTO regulatory_decision "
                "(decision_id, session_id, approved_bids, rejected_bids, "
                "fairness_score, compliance_flags, regulatory_signature) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    decision_id, session_id,
                    json.dumps(approved), json.dumps(rejected),
                    fairness_score,
                    json.dumps(compliance_flags),
                    hashlib.sha256(f"{session_id}:{self.clerk_did}".encode()).hexdigest(),
                ),
            )
            conn.commit()
        finally:
            conn.close()

        # Build and log MSG5
        msg5 = RegulatoryDecision(
            session_id=session_id,
            approved_bids=approved,
            rejected_bids=rejected,
            fairness_score=fairness_score,
            compliance_flags=[f["flag"] for f in compliance_flags],
            regulatory_signature=hashlib.sha256(
                f"{session_id}:{self.clerk_did}".encode()
            ).hexdigest(),
        )
        log_message(self.db_path, session_id, msg5, sender_did=self.clerk_did)

        return {
            "approved_bids": approved,
            "rejected_bids": rejected,
            "fairness_score": fairness_score,
            "compliance_flags": compliance_flags,
        }

    # ------------------------------------------------------------------
    # Fairness check
    # ------------------------------------------------------------------

    def check_fairness(self, session_id: str) -> dict:
        """Run HHI fairness check on approved bids."""
        conn = self._connect()
        try:
            bids = conn.execute(
                "SELECT bidder_did FROM bid "
                "WHERE session_id = ? AND status = 'approved'",
                (session_id,),
            ).fetchall()
        finally:
            conn.close()

        if not bids:
            return {
                "score": 1000,
                "passed": True,
                "max_share": 0.0,
                "violator": None,
            }

        # Count assignments per bidder
        counts: dict[str, int] = {}
        for b in bids:
            did = b["bidder_did"]
            counts[did] = counts.get(did, 0) + 1

        total = sum(counts.values())
        shares = {k: v / total for k, v in counts.items()}

        result = check_fairness(shares)
        return {
            "score": result.score,
            "passed": result.passed,
            "max_share": result.max_share,
            "violator": result.violator,
        }

    # ------------------------------------------------------------------
    # Re-proposal
    # ------------------------------------------------------------------

    def request_reproposal(self, session_id: str, reason: str) -> bool:
        """Request re-proposal (max 2 per epoch).

        Returns True if allowed, False if max reached.
        """
        conn = self._connect()
        try:
            # Count existing re-proposals for this session
            count = conn.execute(
                "SELECT COUNT(*) FROM message_log "
                "WHERE session_id = ? AND msg_type = 'REPROPOSAL_REQUEST'",
                (session_id,),
            ).fetchone()[0]

            if count >= 2:
                return False

            # Log the re-proposal request
            conn.execute(
                "INSERT INTO message_log "
                "(session_id, msg_type, sender_did, receiver, payload) "
                "VALUES (?, 'REPROPOSAL_REQUEST', ?, 'session', ?)",
                (session_id, self.clerk_did, json.dumps({"reason": reason})),
            )
            conn.commit()
            return True
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # Co-sign approval
    # ------------------------------------------------------------------

    def co_sign_approval(self, session_id: str, spec_id: str) -> str:
        """Generate Regulator's co-signature for MSG7."""
        sig_data = f"{session_id}:{spec_id}:{self.clerk_did}"
        return hashlib.sha256(sig_data.encode()).hexdigest()
