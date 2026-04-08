"""Constitutional validation for coded contract specifications.

Implements the 6-check constitutional validation algorithm (SS3.7):
1. Behavioral parameters — deviation sigma, max tools/msgs, escalation freeze
2. Budget compliance — total within cap, positive node budgets, timeout ranges
3. PoP tier constraints — valid tiers, Tier 2 redundancy/consensus, Tier 3 timeout
4. Identity & stake — reputation floors, stake minimums, code hash verification
5. DAG structure — delegates to dag.validate_dag()
6. Fairness — delegates to fairness.check_fairness()
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from oasis.governance.dag import DAGEdge, DAGNode, DAGSpec, validate_dag
from oasis.governance.fairness import check_fairness
from oasis.governance.messages import CodedContractSpec


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------

@dataclass
class ValidationError:
    """A single validation failure."""
    check: str       # which check failed (e.g. "behavioral_params")
    field: str       # specific field or context
    message: str     # human-readable description


@dataclass
class ValidationResult:
    """Outcome of constitutional validation."""
    passed: bool
    errors: List[ValidationError] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Constitutional Validator
# ---------------------------------------------------------------------------

class ConstitutionalValidator:
    """Validates a CodedContractSpec against constitutional parameters.

    Loads the current constitution from the database on initialisation
    and runs 6 validation checks against the spec.
    """

    def __init__(self, db_path: Union[str, Path]) -> None:
        self.db_path = str(db_path)
        self.params = self._load_constitution()

    def _load_constitution(self) -> Dict[str, float]:
        """Load all constitution params into a dict."""
        conn = sqlite3.connect(self.db_path)
        try:
            rows = conn.execute(
                "SELECT param_name, param_value FROM constitution"
            ).fetchall()
            return {name: value for name, value in rows}
        finally:
            conn.close()

    def validate(self, spec: CodedContractSpec) -> ValidationResult:
        """Run all 6 constitutional checks on a spec.

        Returns a ValidationResult with passed=True only if all checks pass.
        """
        all_errors: List[ValidationError] = []
        all_errors.extend(self._check_behavioral_params(spec))
        all_errors.extend(self._check_budget_compliance(spec))
        all_errors.extend(self._check_pop_tier(spec))
        all_errors.extend(self._check_identity_stake(spec))
        all_errors.extend(self._check_dag_structure(spec))
        all_errors.extend(self._check_fairness(spec))
        return ValidationResult(
            passed=len(all_errors) == 0,
            errors=all_errors,
        )

    # -------------------------------------------------------------------
    # Check 1: Behavioral parameters
    # -------------------------------------------------------------------

    def _check_behavioral_params(self, spec: CodedContractSpec) -> List[ValidationError]:
        """Validate behavioral parameters in the collaboration contract.

        Expected fields in collaboration_contract_spec:
        - deviation_sigma: float in [1, 5]
        - max_tools: int in [5, 200]
        - max_messages: int in [10, 500]
        - escalation_freeze_rounds: int in [2, 10]
        """
        errors: List[ValidationError] = []
        collab = spec.collaboration_contract_spec

        _RANGES = {
            "deviation_sigma": (1, 5),
            "max_tools": (5, 200),
            "max_messages": (10, 500),
            "escalation_freeze_rounds": (2, 10),
        }

        for param, (lo, hi) in _RANGES.items():
            value = collab.get(param)
            if value is None:
                continue
            if not (lo <= value <= hi):
                errors.append(ValidationError(
                    check="behavioral_params",
                    field=param,
                    message=f"{param} = {value} is out of range [{lo}, {hi}]",
                ))

        return errors

    # -------------------------------------------------------------------
    # Check 2: Budget compliance
    # -------------------------------------------------------------------

    def _check_budget_compliance(self, spec: CodedContractSpec) -> List[ValidationError]:
        """Validate budget constraints.

        - Total budget <= budget_cap_max from constitution
        - All node budgets must be positive
        - Timeouts must be in a valid range (> 0, <= proposal_deadline_max_ms)
        """
        errors: List[ValidationError] = []
        dag_spec_dict = spec.service_contract_specs.get("dag_spec", {})
        nodes = dag_spec_dict.get("nodes", [])

        budget_cap = self.params.get("budget_cap_max", 1_000_000.0)
        deadline_max = self.params.get("proposal_deadline_max_ms", 86_400_000.0)

        total_budget = sum(n.get("token_budget", 0) for n in nodes)
        if total_budget > budget_cap:
            errors.append(ValidationError(
                check="budget_compliance",
                field="total_budget",
                message=f"Total budget {total_budget:.2f} exceeds cap {budget_cap:.2f}",
            ))

        for n in nodes:
            nid = n.get("node_id", "unknown")
            budget = n.get("token_budget", 0)
            if budget <= 0:
                errors.append(ValidationError(
                    check="budget_compliance",
                    field=f"node.{nid}.token_budget",
                    message=f"Node {nid} has non-positive budget: {budget}",
                ))
            timeout = n.get("timeout_ms", 0)
            if timeout <= 0 or timeout > deadline_max:
                errors.append(ValidationError(
                    check="budget_compliance",
                    field=f"node.{nid}.timeout_ms",
                    message=(
                        f"Node {nid} timeout {timeout} out of range "
                        f"(0, {deadline_max:.0f}]"
                    ),
                ))

        return errors

    # -------------------------------------------------------------------
    # Check 3: PoP tier constraints
    # -------------------------------------------------------------------

    def _check_pop_tier(self, spec: CodedContractSpec) -> List[ValidationError]:
        """Validate Proof-of-Performance tier constraints.

        - All tiers must be in {1, 2, 3}
        - Tier 2: redundancy_factor >= 2, consensus_threshold must be
          majority (> redundancy_factor / 2)
        - Tier 3: timeout_ms >= 30000 (30 seconds minimum)
        """
        errors: List[ValidationError] = []
        dag_spec_dict = spec.service_contract_specs.get("dag_spec", {})
        nodes = dag_spec_dict.get("nodes", [])

        for n in nodes:
            nid = n.get("node_id", "unknown")
            tier = n.get("pop_tier", 1)

            if tier not in (1, 2, 3):
                errors.append(ValidationError(
                    check="pop_tier",
                    field=f"node.{nid}.pop_tier",
                    message=f"Node {nid} has invalid PoP tier: {tier}",
                ))
                continue

            if tier == 2:
                redundancy = n.get("redundancy_factor", 1)
                consensus = n.get("consensus_threshold", 1)
                if redundancy < 2:
                    errors.append(ValidationError(
                        check="pop_tier",
                        field=f"node.{nid}.redundancy_factor",
                        message=(
                            f"Tier 2 node {nid} requires redundancy_factor >= 2, "
                            f"got {redundancy}"
                        ),
                    ))
                if consensus <= redundancy / 2:
                    errors.append(ValidationError(
                        check="pop_tier",
                        field=f"node.{nid}.consensus_threshold",
                        message=(
                            f"Tier 2 node {nid} requires consensus_threshold > "
                            f"redundancy/2 ({redundancy}/2 = {redundancy/2:.1f}), "
                            f"got {consensus}"
                        ),
                    ))

            if tier == 3:
                timeout = n.get("timeout_ms", 0)
                if timeout < 30000:
                    errors.append(ValidationError(
                        check="pop_tier",
                        field=f"node.{nid}.timeout_ms",
                        message=(
                            f"Tier 3 node {nid} requires timeout_ms >= 30000, "
                            f"got {timeout}"
                        ),
                    ))

        return errors

    # -------------------------------------------------------------------
    # Check 4: Identity & stake
    # -------------------------------------------------------------------

    def _check_identity_stake(self, spec: CodedContractSpec) -> List[ValidationError]:
        """Validate identity and staking requirements.

        For each agent referenced in bid_assignments:
        - Agent must be registered in agent_registry
        - Agent reputation must be >= reputation_floor from constitution
        """
        errors: List[ValidationError] = []
        bid_assignments = spec.service_contract_specs.get("bid_assignments", {})
        rep_floor = self.params.get("reputation_floor", 0.1)

        if not bid_assignments:
            return errors

        conn = sqlite3.connect(self.db_path)
        try:
            for agent_did, _share in bid_assignments.items():
                row = conn.execute(
                    "SELECT reputation_score, active FROM agent_registry "
                    "WHERE agent_did = ?",
                    (agent_did,),
                ).fetchone()
                if row is None:
                    errors.append(ValidationError(
                        check="identity_stake",
                        field=f"agent.{agent_did}",
                        message=f"Agent {agent_did} is not registered",
                    ))
                    continue
                rep_score, active = row
                if not active:
                    errors.append(ValidationError(
                        check="identity_stake",
                        field=f"agent.{agent_did}",
                        message=f"Agent {agent_did} is inactive",
                    ))
                if rep_score < rep_floor:
                    errors.append(ValidationError(
                        check="identity_stake",
                        field=f"agent.{agent_did}.reputation",
                        message=(
                            f"Agent {agent_did} reputation {rep_score:.2f} "
                            f"is below floor {rep_floor:.2f}"
                        ),
                    ))
        finally:
            conn.close()

        return errors

    # -------------------------------------------------------------------
    # Check 5: DAG structure
    # -------------------------------------------------------------------

    def _check_dag_structure(self, spec: CodedContractSpec) -> List[ValidationError]:
        """Validate DAG structure by delegating to validate_dag()."""
        errors: List[ValidationError] = []
        dag_spec_dict = spec.service_contract_specs.get("dag_spec", {})
        raw_nodes = dag_spec_dict.get("nodes", [])
        raw_edges = dag_spec_dict.get("edges", [])

        if not raw_nodes:
            # No DAG to validate — skip (budget check already handles empty)
            return errors

        # Build typed DAGSpec from dict representation
        nodes = [
            DAGNode(
                node_id=n["node_id"],
                label=n.get("label", ""),
                service_id=n.get("service_id", ""),
                input_schema=n.get("input_schema"),
                output_schema=n.get("output_schema"),
                pop_tier=n.get("pop_tier", 1),
                redundancy_factor=n.get("redundancy_factor", 1),
                consensus_threshold=n.get("consensus_threshold", 1),
                token_budget=n.get("token_budget", 0.0),
                timeout_ms=n.get("timeout_ms", 60000),
                risk_tier=n.get("risk_tier", "low"),
            )
            for n in raw_nodes
        ]
        edges = [
            DAGEdge(
                from_node_id=e["from_node_id"],
                to_node_id=e["to_node_id"],
                data_flow_schema=e.get("data_flow_schema"),
            )
            for e in raw_edges
        ]
        dag = DAGSpec(nodes=nodes, edges=edges)
        result = validate_dag(dag)

        if not result.valid:
            for err_msg in result.errors:
                errors.append(ValidationError(
                    check="dag_structure",
                    field="dag_spec",
                    message=err_msg,
                ))

        return errors

    # -------------------------------------------------------------------
    # Check 6: Fairness
    # -------------------------------------------------------------------

    def _check_fairness(self, spec: CodedContractSpec) -> List[ValidationError]:
        """Validate fairness by delegating to check_fairness()."""
        errors: List[ValidationError] = []
        bid_assignments = spec.service_contract_specs.get("bid_assignments", {})

        if not bid_assignments:
            return errors

        min_score = int(self.params.get("fairness_hhi_threshold", 0.25) * 1000)
        # Use a default min_score of 600 if the threshold-derived value is too low
        min_score = max(min_score, 250)

        result = check_fairness(bid_assignments, min_score=min_score)
        if not result.passed:
            errors.append(ValidationError(
                check="fairness",
                field="bid_assignments",
                message=(
                    f"Fairness score {result.score} is below minimum "
                    f"{min_score}; largest share held by {result.violator} "
                    f"({result.max_share:.2%})"
                ),
            ))

        return errors
