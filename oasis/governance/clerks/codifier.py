"""Codifier clerk — spec compilation and constitutional validation.

Handles:
- Compiling deployment specs from proposals + approved bids (MSG6)
- Running constitutional validation (6 checks)
- Verifying deployed contracts match specifications
- Layer 2: semantic consistency validation between proposal and spec
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from oasis.governance.clerks.base import BaseClerk
from oasis.governance.clerks.llm_interface import LLMError
from oasis.governance.constitutional import ConstitutionalValidator, ValidationResult
from oasis.governance.messages import CodedContractSpec, DAGProposal, log_message


class Codifier(BaseClerk):
    """Codifier clerk — Layer 1 spec compilation + Layer 2 semantic validation."""

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

    # ------------------------------------------------------------------
    # Layer 2: Semantic consistency validation
    # ------------------------------------------------------------------

    def layer2_reason(self, context: dict) -> Optional[dict]:
        """Validate semantic consistency between proposal rationale and spec.

        Context keys:
            proposal_rationale: str describing what the proposal intends
            spec: dict of CodedContractSpec fields
            service_specs: list[dict] of service assignments

        Returns:
            dict with {semantically_consistent, issues} or None if LLM disabled.
        """
        if not self.llm_enabled or self.llm is None:
            return None

        rationale = context.get("proposal_rationale", "")
        spec = context.get("spec", {})
        service_specs = context.get("service_specs", [])

        issues: list[str] = []

        # --- Heuristic 1: Check that spec has services matching rationale keywords ---
        if rationale and service_specs:
            # Basic keyword extraction from rationale
            rationale_lower = rationale.lower()
            service_labels = [
                s.get("service_id", "") or s.get("label", "")
                for s in service_specs
            ]
            service_text = " ".join(service_labels).lower()

            # If rationale mentions specific actions but no matching service exists
            action_keywords = ["collect", "analyze", "process", "validate", "transform"]
            mentioned_actions = [kw for kw in action_keywords if kw in rationale_lower]
            unmatched = [a for a in mentioned_actions if a not in service_text]
            if unmatched and len(unmatched) > len(mentioned_actions) / 2:
                issues.append(
                    f"Rationale mentions actions ({', '.join(unmatched)}) "
                    f"not reflected in service specs"
                )

        # --- Heuristic 2: Budget sanity check ---
        collab = spec.get("collaboration_contract_spec", {})
        total_budget = collab.get("total_budget", 0)
        service_budget_sum = sum(s.get("token_budget", 0) for s in service_specs)
        if total_budget > 0 and service_budget_sum > total_budget:
            issues.append(
                f"Service budgets ({service_budget_sum}) exceed "
                f"total budget ({total_budget})"
            )

        # --- Heuristic 3: Empty or missing fields ---
        if not rationale or not rationale.strip():
            issues.append("Proposal rationale is empty")

        if not service_specs:
            issues.append("No service specs provided")

        # --- LLM semantic validation ---
        try:
            prompt = (
                f"Semantic consistency check.\n"
                f"Proposal rationale: {rationale}\n"
                f"Service specs: {json.dumps(service_specs[:5], default=str)}\n"
                f"Collaboration spec: {json.dumps(collab, default=str)}\n\n"
                f"Does the spec faithfully implement the proposal's intent? "
                f"Flag any semantic mismatches or ambiguities."
            )
            llm_response = self.llm.query(prompt, context)

            # Parse LLM response for issues
            response_lower = llm_response.lower()
            if any(kw in response_lower for kw in ["mismatch", "inconsisten", "conflict", "ambig"]):
                issues.append(f"LLM semantic check: {llm_response}")
        except LLMError:
            pass  # degrade gracefully

        return {
            "semantically_consistent": len(issues) == 0,
            "issues": issues,
        }
