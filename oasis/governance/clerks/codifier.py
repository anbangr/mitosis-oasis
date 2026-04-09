"""Codifier clerk — spec compilation and constitutional validation.

Handles:
- Compiling deployment specs from proposals + approved bids (MSG6)
- Running constitutional validation (6 checks)
- Verifying deployed contracts match specifications
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any

from oasis.governance.clerks.base import BaseClerk
from oasis.governance.constitutional import ConstitutionalValidator, ValidationResult
from oasis.governance.messages import CodedContractSpec, DAGProposal, log_message


class Codifier(BaseClerk):
    """Codifier clerk — Layer 1 spec compilation and validation."""

    # ------------------------------------------------------------------
    # Layer 1 dispatch
    # ------------------------------------------------------------------

    def layer1_process(self, msg: Any) -> dict:
        """Dispatch MSG6 specs for validation."""
        if isinstance(msg, CodedContractSpec):
            result = self.run_constitutional_validation(msg)
            return {
                "passed": result.passed,
                "result": result,
                "errors": [
                    {"check": e.check, "field": e.field, "message": e.message}
                    for e in result.errors
                ],
            }
        return {"passed": False, "result": None, "errors": ["Unsupported message type"]}

    # ------------------------------------------------------------------
    # Spec compilation
    # ------------------------------------------------------------------

    def compile_spec(
        self,
        session_id: str,
        proposal: DAGProposal,
        approved_bids: list[dict],
    ) -> CodedContractSpec:
        """Compile deployment specification from proposal + approved bids.

        Merges proposal DAG structure with selected bids to produce MSG6.
        """
        dag_spec = proposal.dag_spec
        nodes = dag_spec.get("nodes", [])
        edges = dag_spec.get("edges", [])

        # Build bid assignments: node_id -> bidder_did
        bid_map: dict[str, dict] = {}
        bid_assignments: dict[str, float] = {}
        for bid in approved_bids:
            node_id = bid["task_node_id"]
            bid_map[node_id] = bid
            bidder = bid["bidder_did"]
            bid_assignments[bidder] = bid_assignments.get(bidder, 0) + 1

        # Normalise to shares
        total = sum(bid_assignments.values())
        if total > 0:
            bid_assignments = {k: v / total for k, v in bid_assignments.items()}

        # Build service contract specs — merge node + bid info
        service_specs: list[dict] = []
        for node in nodes:
            nid = node["node_id"]
            bid = bid_map.get(nid, {})
            service_specs.append({
                "node_id": nid,
                "service_id": bid.get("service_id", node.get("service_id", "")),
                "bidder_did": bid.get("bidder_did", ""),
                "code_hash": bid.get("proposed_code_hash", ""),
                "stake_amount": bid.get("stake_amount", 0.0),
                "pop_tier": node.get("pop_tier", 1),
                "token_budget": node.get("token_budget", 0.0),
                "timeout_ms": node.get("timeout_ms", 60000),
            })

        # Build collaboration contract spec
        collab_spec = {
            "session_id": session_id,
            "proposer_did": proposal.proposer_did,
            "total_budget": proposal.token_budget_total,
            "deadline_ms": proposal.deadline_ms,
            "deviation_sigma": 3.0,
            "max_tools": 50,
            "max_messages": 100,
            "escalation_freeze_rounds": 3,
        }

        # Build guardian module spec
        guardian_spec = {
            "budget_enforcement": True,
            "timeout_enforcement": True,
            "escalation_policy": "freeze_and_review",
        }

        # Build verification module spec
        verification_spec = {
            "code_hash_verification": True,
            "output_validation": True,
            "pop_tier_enforcement": True,
        }

        # Build gate module spec
        gate_spec = {
            "approval_required": True,
            "dual_signature": True,
            "constitutional_validation": True,
        }

        spec_id = f"spec-{uuid.uuid4().hex[:8]}"
        validation_proof = f"compiled-{session_id}-{spec_id}"

        msg6 = CodedContractSpec(
            session_id=session_id,
            collaboration_contract_spec=collab_spec,
            guardian_module_spec=guardian_spec,
            verification_module_spec=verification_spec,
            gate_module_spec=gate_spec,
            service_contract_specs={
                "dag_spec": {"nodes": nodes, "edges": edges},
                "service_assignments": service_specs,
                "bid_assignments": bid_assignments,
            },
            validation_proof=validation_proof,
        )

        # Store in DB
        conn = self._connect()
        try:
            conn.execute(
                "INSERT INTO contract_spec "
                "(spec_id, session_id, collaboration_contract_spec, "
                "guardian_module_spec, verification_module_spec, "
                "gate_module_spec, service_contract_specs, "
                "validation_proof, status) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'draft')",
                (
                    spec_id, session_id,
                    json.dumps(collab_spec),
                    json.dumps(guardian_spec),
                    json.dumps(verification_spec),
                    json.dumps(gate_spec),
                    json.dumps(msg6.service_contract_specs),
                    validation_proof,
                ),
            )
            conn.commit()
        finally:
            conn.close()

        log_message(self.db_path, session_id, msg6, sender_did=self.clerk_did)
        return msg6

    # ------------------------------------------------------------------
    # Constitutional validation
    # ------------------------------------------------------------------

    def run_constitutional_validation(self, spec: CodedContractSpec) -> ValidationResult:
        """Run all 6 constitutional checks on a spec.

        Delegates to ConstitutionalValidator.
        """
        validator = ConstitutionalValidator(self.db_path)
        result = validator.validate(spec)

        # Update contract_spec status if stored
        conn = self._connect()
        try:
            status = "validated" if result.passed else "rejected"
            conn.execute(
                "UPDATE contract_spec SET status = ? "
                "WHERE session_id = ? AND validation_proof = ?",
                (status, spec.session_id, spec.validation_proof),
            )
            conn.commit()
        finally:
            conn.close()

        return result

    # ------------------------------------------------------------------
    # Deployment verification
    # ------------------------------------------------------------------

    def verify_deployment(
        self,
        spec: CodedContractSpec,
        deployed_contract: dict,
    ) -> dict:
        """Verify a deployed contract matches its specification.

        Checks parameter-by-parameter equality.
        """
        mismatches: list[str] = []

        # Check required top-level fields
        expected_fields = [
            "collaboration_contract_spec",
            "guardian_module_spec",
            "verification_module_spec",
            "gate_module_spec",
            "service_contract_specs",
        ]

        for field_name in expected_fields:
            spec_value = getattr(spec, field_name, None)
            deployed_value = deployed_contract.get(field_name)

            if deployed_value is None:
                mismatches.append(f"Missing field: {field_name}")
                continue

            if spec_value != deployed_value:
                mismatches.append(f"Mismatch in {field_name}")

        return {
            "passed": len(mismatches) == 0,
            "mismatches": mismatches,
        }
