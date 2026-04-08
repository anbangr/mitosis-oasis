"""Tests for constitutional behavioral parameter validation."""
from pathlib import Path

from oasis.governance.constitutional import ConstitutionalValidator
from oasis.governance.messages import CodedContractSpec


def _make_spec(collab: dict) -> CodedContractSpec:
    """Build a minimal CodedContractSpec with given collaboration params."""
    return CodedContractSpec(
        session_id="sess-1",
        collaboration_contract_spec=collab,
        guardian_module_spec={"mode": "passive"},
        verification_module_spec={"type": "hash"},
        gate_module_spec={"threshold": 0.5},
        service_contract_specs={"dag_spec": {"nodes": [], "edges": []}},
        validation_proof="proof-abc",
    )


def test_all_params_in_range(governance_db: Path):
    """All behavioral params within valid ranges pass."""
    validator = ConstitutionalValidator(governance_db)
    spec = _make_spec({
        "deviation_sigma": 3.0,
        "max_tools": 50,
        "max_messages": 100,
        "escalation_freeze_rounds": 5,
    })
    result = validator._check_behavioral_params(spec)
    assert result == []


def test_sigma_out_of_range(governance_db: Path):
    """Deviation sigma outside [1, 5] should produce an error."""
    validator = ConstitutionalValidator(governance_db)
    spec = _make_spec({"deviation_sigma": 0.5})
    errors = validator._check_behavioral_params(spec)
    assert len(errors) == 1
    assert "deviation_sigma" in errors[0].field


def test_tools_out_of_range(governance_db: Path):
    """max_tools outside [5, 200] should produce an error."""
    validator = ConstitutionalValidator(governance_db)
    spec = _make_spec({"max_tools": 250})
    errors = validator._check_behavioral_params(spec)
    assert len(errors) == 1
    assert "max_tools" in errors[0].field


def test_multiple_violations(governance_db: Path):
    """Multiple out-of-range params produce multiple errors."""
    validator = ConstitutionalValidator(governance_db)
    spec = _make_spec({
        "deviation_sigma": 10,
        "max_tools": 1,
        "max_messages": 5,
        "escalation_freeze_rounds": 20,
    })
    errors = validator._check_behavioral_params(spec)
    assert len(errors) == 4
