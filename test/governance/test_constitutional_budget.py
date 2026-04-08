"""Tests for constitutional budget compliance validation."""
from pathlib import Path

from oasis.governance.constitutional import ConstitutionalValidator
from oasis.governance.messages import CodedContractSpec


def _make_spec(nodes: list) -> CodedContractSpec:
    """Build a CodedContractSpec with given DAG nodes."""
    return CodedContractSpec(
        session_id="sess-1",
        collaboration_contract_spec={},
        guardian_module_spec={"mode": "passive"},
        verification_module_spec={"type": "hash"},
        gate_module_spec={"threshold": 0.5},
        service_contract_specs={
            "dag_spec": {"nodes": nodes, "edges": []},
        },
        validation_proof="proof-abc",
    )


def test_valid_budget(governance_db: Path):
    """Nodes with positive budgets within cap pass."""
    validator = ConstitutionalValidator(governance_db)
    spec = _make_spec([
        {"node_id": "A", "token_budget": 500.0, "timeout_ms": 60000},
        {"node_id": "B", "token_budget": 300.0, "timeout_ms": 60000},
    ])
    errors = validator._check_budget_compliance(spec)
    assert errors == []


def test_exceeds_cap(governance_db: Path):
    """Total budget exceeding the cap should fail."""
    validator = ConstitutionalValidator(governance_db)
    spec = _make_spec([
        {"node_id": "A", "token_budget": 600_000.0, "timeout_ms": 60000},
        {"node_id": "B", "token_budget": 500_000.0, "timeout_ms": 60000},
    ])
    errors = validator._check_budget_compliance(spec)
    assert len(errors) >= 1
    assert any("exceeds cap" in e.message.lower() for e in errors)


def test_negative_node_budget(governance_db: Path):
    """A node with negative budget should fail."""
    validator = ConstitutionalValidator(governance_db)
    spec = _make_spec([
        {"node_id": "A", "token_budget": -10.0, "timeout_ms": 60000},
    ])
    errors = validator._check_budget_compliance(spec)
    assert len(errors) >= 1
    assert any("non-positive" in e.message.lower() for e in errors)
