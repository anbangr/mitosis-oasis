"""P6 — Test Codifier.run_constitutional_validation."""
from pathlib import Path

from oasis.governance.clerks.codifier import Codifier
from oasis.governance.messages import CodedContractSpec


def _make_valid_spec(session_id: str = "sess-val") -> CodedContractSpec:
    return CodedContractSpec(
        session_id=session_id,
        collaboration_contract_spec={
            "deviation_sigma": 3.0,
            "max_tools": 50,
            "max_messages": 100,
            "escalation_freeze_rounds": 3,
        },
        guardian_module_spec={"budget_enforcement": True},
        verification_module_spec={"code_hash_verification": True},
        gate_module_spec={"approval_required": True},
        service_contract_specs={
            "dag_spec": {
                "nodes": [
                    {"node_id": "root", "label": "Root", "service_id": "svc",
                     "pop_tier": 1, "token_budget": 100.0, "timeout_ms": 60000},
                ],
                "edges": [],
            },
            "bid_assignments": {},
        },
        validation_proof="test-proof",
    )


def test_constitutional_validation_delegated(governance_db: Path):
    """run_constitutional_validation delegates to ConstitutionalValidator."""
    cod = Codifier(str(governance_db), "did:oasis:clerk-codifier")
    spec = _make_valid_spec()
    result = cod.run_constitutional_validation(spec)
    # Should delegate and return a ValidationResult
    assert hasattr(result, "passed")
    assert hasattr(result, "errors")


def test_pass_through_result(governance_db: Path):
    """Valid spec passes constitutional validation."""
    cod = Codifier(str(governance_db), "did:oasis:clerk-codifier")
    spec = _make_valid_spec()
    result = cod.run_constitutional_validation(spec)
    assert result.passed is True
    assert len(result.errors) == 0


def test_failure_with_structured_errors(governance_db: Path):
    """Invalid spec returns structured ValidationErrors."""
    cod = Codifier(str(governance_db), "did:oasis:clerk-codifier")
    spec = CodedContractSpec(
        session_id="sess-val",
        collaboration_contract_spec={
            "deviation_sigma": 100.0,  # Out of range [1, 5]
        },
        guardian_module_spec={"x": 1},
        verification_module_spec={"x": 1},
        gate_module_spec={"x": 1},
        service_contract_specs={
            "dag_spec": {
                "nodes": [
                    {"node_id": "root", "label": "Root", "service_id": "svc",
                     "pop_tier": 1, "token_budget": 100.0, "timeout_ms": 60000},
                ],
                "edges": [],
            },
            "bid_assignments": {},
        },
        validation_proof="test-proof",
    )
    result = cod.run_constitutional_validation(spec)
    assert result.passed is False
    assert len(result.errors) > 0
    # Each error should have check, field, message
    err = result.errors[0]
    assert hasattr(err, "check")
    assert hasattr(err, "field")
    assert hasattr(err, "message")
