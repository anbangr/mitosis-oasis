"""Speaker clerk — proposals, deliberation, and voting.

Handles:
- Receiving and validating proposals (MSG3)
- Straw polls (pre-deliberation preferences)
- Deliberation rounds (max 3, randomized speaking order)
- Formal voting via Copeland method
- Coordination detection (Kendall tau)
- Issuing approval signatures (MSG7 half)
"""
from __future__ import annotations

import hashlib
import json
import random
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from oasis.governance.clerks.base import BaseClerk
from oasis.governance.dag import DAGEdge, DAGNode, DAGSpec, CycleError, topological_sort, validate_dag
from oasis.governance.messages import DAGProposal, log_message
from oasis.governance.voting import CopelandVoting, coordination_detection, kendall_tau


class Speaker(BaseClerk):
    """Speaker clerk — Layer 1 proposal and voting management."""

    # ------------------------------------------------------------------
    # Layer 1 dispatch
    # ------------------------------------------------------------------

    def layer1_process(self, msg: Any) -> dict:
        """Dispatch MSG3 proposals for validation."""
        if isinstance(msg, DAGProposal):
            result = self.receive_proposal(msg.session_id, msg)
            return {
                "passed": result["passed"],
                "result": result,
                "errors": result.get("errors", []),
            }
        return {"passed": False, "result": None, "errors": ["Unsupported message type"]}

    # ------------------------------------------------------------------
    # Proposal handling
    # ------------------------------------------------------------------

    def receive_proposal(self, session_id: str, proposal: DAGProposal) -> dict:
        """Validate and accept a DAG proposal.

        Checks:
        1. DAG is acyclic (topological sort succeeds)
        2. Budget <= budget_cap_max
        3. Deadline <= proposal_deadline_max_ms
        """
        errors: list[str] = []
        dag_spec_dict = proposal.dag_spec

        # Build DAGSpec from dict
        raw_nodes = dag_spec_dict.get("nodes", [])
        raw_edges = dag_spec_dict.get("edges", [])
        nodes = [
            DAGNode(
                node_id=n["node_id"],
                label=n.get("label", ""),
                service_id=n.get("service_id", ""),
                pop_tier=n.get("pop_tier", 1),
                token_budget=n.get("token_budget", 0.0),
                timeout_ms=n.get("timeout_ms", 60000),
            )
            for n in raw_nodes
        ]
        edges = [
            DAGEdge(
                from_node_id=e["from_node_id"],
                to_node_id=e["to_node_id"],
            )
            for e in raw_edges
        ]
        dag = DAGSpec(nodes=nodes, edges=edges)

        # 1. Acyclicity
        try:
            topo_order = topological_sort(dag)
        except CycleError:
            errors.append("DAG contains a cycle")
            return {
                "passed": False,
                "proposal_id": None,
                "topological_order": [],
                "errors": errors,
            }

        # Full DAG validation
        dag_result = validate_dag(dag)
        if not dag_result.valid:
            errors.extend(dag_result.errors)

        # 2. Budget check
        conn = self._connect()
        try:
            cap_row = conn.execute(
                "SELECT param_value FROM constitution WHERE param_name = 'budget_cap_max'"
            ).fetchone()
            budget_cap = cap_row[0] if cap_row else 1_000_000.0

            if proposal.token_budget_total > budget_cap:
                errors.append(
                    f"Budget {proposal.token_budget_total:.2f} exceeds cap {budget_cap:.2f}"
                )

            # 3. Deadline check
            deadline_row = conn.execute(
                "SELECT param_value FROM constitution WHERE param_name = 'proposal_deadline_max_ms'"
            ).fetchone()
            deadline_max = deadline_row[0] if deadline_row else 86_400_000.0

            if proposal.deadline_ms > deadline_max:
                errors.append(
                    f"Deadline {proposal.deadline_ms}ms exceeds max {deadline_max:.0f}ms"
                )
        finally:
            conn.close()

        if errors:
            return {
                "passed": False,
                "proposal_id": None,
                "topological_order": [],
                "errors": errors,
            }

        # Store proposal
        proposal_id = f"prop-{uuid.uuid4().hex[:8]}"
        conn = self._connect()
        try:
            conn.execute(
                "INSERT INTO proposal "
                "(proposal_id, session_id, proposer_did, dag_spec, rationale, "
                "token_budget_total, deadline_ms, status) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, 'submitted')",
                (
                    proposal_id,
                    session_id,
                    proposal.proposer_did,
                    json.dumps(proposal.dag_spec),
                    proposal.rationale,
                    proposal.token_budget_total,
                    proposal.deadline_ms,
                ),
            )
            # Store DAG nodes and edges
            for node in nodes:
                conn.execute(
                    "INSERT INTO dag_node "
                    "(node_id, proposal_id, label, service_id, pop_tier, "
                    "token_budget, timeout_ms) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (
                        node.node_id, proposal_id, node.label,
                        node.service_id, node.pop_tier,
                        node.token_budget, node.timeout_ms,
                    ),
                )
            for edge in edges:
                conn.execute(
                    "INSERT INTO dag_edge "
                    "(proposal_id, from_node_id, to_node_id) VALUES (?, ?, ?)",
                    (proposal_id, edge.from_node_id, edge.to_node_id),
                )
            conn.commit()
        finally:
            conn.close()

        log_message(self.db_path, session_id, proposal, sender_did=proposal.proposer_did)

        return {
            "passed": True,
            "proposal_id": proposal_id,
            "topological_order": topo_order,
            "errors": [],
        }

    # ------------------------------------------------------------------
    # Straw poll
    # ------------------------------------------------------------------

    def open_straw_poll(self, session_id: str) -> dict:
        """Open a pre-deliberation straw poll."""
        conn = self._connect()
        try:
            # Get proposals as candidates
            rows = conn.execute(
                "SELECT proposal_id FROM proposal WHERE session_id = ? AND status = 'submitted'",
                (session_id,),
            ).fetchall()
            candidates = [r["proposal_id"] for r in rows]
        finally:
            conn.close()

        return {
            "poll_id": f"poll-{uuid.uuid4().hex[:8]}",
            "candidates": candidates,
            "started_at": datetime.now(timezone.utc).isoformat(),
        }

    def collect_straw_poll(self, session_id: str, ballots: dict) -> dict:
        """Collect straw poll ballots and compute Copeland result.

        Args:
            ballots: {agent_did: [ranking of candidate IDs]}
        """
        if not ballots:
            return {
                "total_votes": 0,
                "copeland_winner": None,
                "scores": {},
                "pairwise_matrix": {},
            }

        # Determine candidates from first ballot
        first_ranking = next(iter(ballots.values()))
        candidates = list(first_ranking)

        cv = CopelandVoting(candidates=candidates)
        for agent_did, ranking in ballots.items():
            cv.add_ballot(agent_did, ranking)

        result = cv.result()

        # Store straw poll ballots in DB
        conn = self._connect()
        try:
            for agent_did, ranking in ballots.items():
                conn.execute(
                    "INSERT INTO straw_poll "
                    "(session_id, agent_did, proposal_id, preference_ranking) "
                    "VALUES (?, ?, ?, ?)",
                    (session_id, agent_did, candidates[0], json.dumps(ranking)),
                )
            conn.commit()
        finally:
            conn.close()

        # Convert tuple keys to strings for serializability
        pw_matrix = {f"{k[0]}|{k[1]}": v for k, v in result.pairwise_matrix.items()}

        return {
            "total_votes": len(ballots),
            "copeland_winner": result.winner,
            "scores": result.scores,
            "pairwise_matrix": pw_matrix,
        }

    # ------------------------------------------------------------------
    # Deliberation
    # ------------------------------------------------------------------

    def open_deliberation_round(self, session_id: str, round_num: int) -> dict:
        """Open a deliberation round (max 3 per session).

        Randomizes speaking order for fairness.
        """
        conn = self._connect()
        try:
            max_rounds_row = conn.execute(
                "SELECT param_value FROM constitution "
                "WHERE param_name = 'max_deliberation_rounds'"
            ).fetchone()
            max_rounds = int(max_rounds_row[0]) if max_rounds_row else 3

            if round_num > max_rounds:
                return {
                    "round_number": round_num,
                    "speaking_order": [],
                    "opened_at": None,
                    "error": f"Max deliberation rounds ({max_rounds}) exceeded",
                }

            # Get attested producers for speaking order
            attested = conn.execute(
                "SELECT DISTINCT ml.sender_did FROM message_log ml "
                "INNER JOIN agent_registry ar ON ml.sender_did = ar.agent_did "
                "WHERE ml.session_id = ? AND ml.msg_type = 'IDENTITY_ATTESTATION' "
                "AND ar.agent_type = 'producer'",
                (session_id,),
            ).fetchall()
            agents = [r["sender_did"] for r in attested]
        finally:
            conn.close()

        # Randomize speaking order
        shuffled = list(agents)
        random.shuffle(shuffled)

        return {
            "round_number": round_num,
            "speaking_order": shuffled,
            "opened_at": datetime.now(timezone.utc).isoformat(),
        }

    def close_deliberation_round(self, session_id: str, round_num: int) -> dict:
        """Close and summarize a deliberation round."""
        conn = self._connect()
        try:
            rows = conn.execute(
                "SELECT COUNT(*) as cnt, COUNT(DISTINCT agent_did) as participants "
                "FROM deliberation_round "
                "WHERE session_id = ? AND round_number = ?",
                (session_id, round_num),
            ).fetchone()
            msg_count = rows["cnt"]
            participant_count = rows["participants"]
        finally:
            conn.close()

        return {
            "round_number": round_num,
            "participant_count": participant_count,
            "message_count": msg_count,
            "summary": f"Round {round_num} completed with {msg_count} messages "
                       f"from {participant_count} participants",
        }

    # ------------------------------------------------------------------
    # Formal voting
    # ------------------------------------------------------------------

    def open_voting(self, session_id: str) -> dict:
        """Open the formal voting phase."""
        conn = self._connect()
        try:
            rows = conn.execute(
                "SELECT proposal_id FROM proposal "
                "WHERE session_id = ? AND status = 'submitted'",
                (session_id,),
            ).fetchall()
            candidates = [r["proposal_id"] for r in rows]
        finally:
            conn.close()

        return {
            "session_id": session_id,
            "candidates": candidates,
            "opened_at": datetime.now(timezone.utc).isoformat(),
        }

    def tabulate_votes(self, session_id: str, ballots: dict) -> dict:
        """Compute Copeland winner and store votes.

        Args:
            ballots: {agent_did: [ranking of candidate IDs]}
        """
        if not ballots:
            return {
                "winner": None,
                "scores": {},
                "quorum_met": False,
                "tiebreak_used": False,
            }

        first_ranking = next(iter(ballots.values()))
        candidates = list(first_ranking)

        cv = CopelandVoting(candidates=candidates)
        for agent_did, ranking in ballots.items():
            cv.add_ballot(agent_did, ranking)

        # Check quorum
        conn = self._connect()
        try:
            total_eligible = conn.execute(
                "SELECT COUNT(*) FROM agent_registry "
                "WHERE agent_type = 'producer' AND active = 1"
            ).fetchone()[0]

            threshold_row = conn.execute(
                "SELECT param_value FROM constitution WHERE param_name = 'quorum_threshold'"
            ).fetchone()
            threshold = threshold_row[0] if threshold_row else 0.51

            quorum = cv.quorum_met(total_eligible, threshold)

            # Store votes
            for agent_did, ranking in ballots.items():
                conn.execute(
                    "INSERT INTO vote (session_id, agent_did, preference_ranking) "
                    "VALUES (?, ?, ?)",
                    (session_id, agent_did, json.dumps(ranking)),
                )
            conn.commit()
        finally:
            conn.close()

        result = cv.result()

        return {
            "winner": result.winner,
            "scores": result.scores,
            "quorum_met": quorum,
            "tiebreak_used": result.tiebreak_used,
        }

    def check_coordination(self, session_id: str) -> dict:
        """Detect coordination/herding between straw poll and final vote.

        Uses Kendall tau correlation.
        """
        conn = self._connect()
        try:
            # Load straw poll rankings
            straw_rows = conn.execute(
                "SELECT agent_did, preference_ranking FROM straw_poll "
                "WHERE session_id = ?",
                (session_id,),
            ).fetchall()
            straw_rankings = {}
            for r in straw_rows:
                straw_rankings[r["agent_did"]] = json.loads(r["preference_ranking"])

            # Load final vote rankings
            vote_rows = conn.execute(
                "SELECT agent_did, preference_ranking FROM vote "
                "WHERE session_id = ?",
                (session_id,),
            ).fetchall()
            final_rankings = {}
            for r in vote_rows:
                final_rankings[r["agent_did"]] = json.loads(r["preference_ranking"])
        finally:
            conn.close()

        if not straw_rankings or not final_rankings:
            return {
                "flagged": False,
                "avg_tau": 0.0,
                "explanation": "Insufficient data for coordination detection",
            }

        flagged, avg_tau = coordination_detection(straw_rankings, final_rankings)

        return {
            "flagged": flagged,
            "avg_tau": avg_tau,
            "explanation": (
                f"Average Kendall tau = {avg_tau:.3f}; "
                f"{'FLAGGED — possible coordination' if flagged else 'no coordination detected'}"
            ),
        }

    # ------------------------------------------------------------------
    # Approval
    # ------------------------------------------------------------------

    def issue_approval(self, session_id: str, spec_id: str) -> dict:
        """Generate Speaker's signature half of MSG7.

        Only allowed if authority check passes for speaker:issue_approval.
        """
        if not self.authority_check("speaker:issue_approval"):
            return {
                "speaker_signature": None,
                "spec_id": spec_id,
                "error": "Unauthorized: speaker:issue_approval not in authority envelope",
            }

        # Generate deterministic signature
        sig_data = f"{session_id}:{spec_id}:{self.clerk_did}"
        signature = hashlib.sha256(sig_data.encode()).hexdigest()

        return {
            "speaker_signature": signature,
            "spec_id": spec_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
