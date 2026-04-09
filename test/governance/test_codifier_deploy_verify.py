"""P6 — Test Codifier.verify_deployment."""
from pathlib import Path

from oasis.governance.clerks.codifier import Codifier
from oasis.governance.messages import CodedContractSpec


def _make_spec() -> CodedContractSpec:
    return CodedContractSpec(
        session_id="sess-deploy",
        collaboration_contract_spec={"session_id": "sess-deploy", "total_budget": 100},
        guardian_module_spec={"budget_enforcement": True},
        verification_module_spec={"code_hash_verification": True},
        gate_module_spec={"approval_required": True},
        service_contract_specs={"dag_spec": {"nodes": [], "edges": []}},
        validation_proof="proof-123",
    )


def test_matching_spec_passes(governance_db: Path):
    """Deployed contract matching spec passes verification."""
    cod = Codifier(str(governance_db), "did:oasis:clerk-codifier")
    spec = _make_spec()
    deployed = {
        "collaboration_contract_spec": {"session_id": "sess-deploy", "total_budget": 100},
        "guardian_module_spec": {"budget_enforcement": True},
        "verification_module_spec": {"code_hash_verification": True},
        "gate_module_spec": {"approval_required": True},
        "service_contract_specs": {"dag_spec": {"nodes": [], "edges": []}},
    }
    result = cod.verify_deployment(spec, deployed)
    assert result["passed"] is True
    assert result["mismatches"] == []


def test_mismatched_param_fails(governance_db: Path):
    """Deployed contract with different params fails verification."""
    cod = Codifier(str(governance_db), "did:oasis:clerk-codifier")
    spec = _make_spec()
    deployed = {
        "collaboration_contract_spec": {"session_id": "sess-deploy", "total_budget": 999},
        "guardian_module_spec": {"budget_enforcement": True},
        "verification_module_spec": {"code_hash_verification": True},
        "gate_module_spec": {"approval_required": True},
        "service_contract_specs": {"dag_spec": {"nodes": [], "edges": []}},
    }
    result = cod.verify_deployment(spec, deployed)
    assert result["passed"] is False
    assert len(result["mismatches"]) > 0
    assert any("collaboration_contract_spec" in m for m in result["mismatches"])


def test_missing_field_fails(governance_db: Path):
    """Deployed contract missing a field fails verification."""
    cod = Codifier(str(governance_db), "did:oasis:clerk-codifier")
    spec = _make_spec()
    deployed = {
        "collaboration_contract_spec": {"session_id": "sess-deploy", "total_budget": 100},
        # Missing guardian_module_spec
        "verification_module_spec": {"code_hash_verification": True},
        "gate_module_spec": {"approval_required": True},
        "service_contract_specs": {"dag_spec": {"nodes": [], "edges": []}},
    }
    result = cod.verify_deployment(spec, deployed)
    assert result["passed"] is False
    assert any("guardian_module_spec" in m for m in result["mismatches"])
