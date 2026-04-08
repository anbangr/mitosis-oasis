"""Tests for constitutional PoP tier validation."""
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


def test_tier_1_valid(governance_db: Path):
    """Tier 1 with default redundancy/consensus is valid."""
    validator = ConstitutionalValidator(governance_db)
    spec = _make_spec([{
        "node_id": "A", "pop_tier": 1,
        "token_budget": 100.0, "timeout_ms": 60000,
    }])
    errors = validator._check_pop_tier(spec)
    assert errors == []


def test_tier_2_redundancy_check(governance_db: Path):
    """Tier 2 requires redundancy_factor >= 2."""
    validator = ConstitutionalValidator(governance_db)
    spec = _make_spec([{
        "node_id": "A", "pop_tier": 2,
        "redundancy_factor": 1, "consensus_threshold": 1,
        "token_budget": 100.0, "timeout_ms": 60000,
    }])
    errors = validator._check_pop_tier(spec)
    assert len(errors) >= 1
    assert any("redundancy_factor" in e.field for e in errors)


def test_tier_2_consensus_majority(governance_db: Path):
    """Tier 2 consensus_threshold must be > redundancy/2."""
    validator = ConstitutionalValidator(governance_db)
    # redundancy=4, consensus=2 means consensus <= 4/2=2.0, should fail
    spec = _make_spec([{
        "node_id": "A", "pop_tier": 2,
        "redundancy_factor": 4, "consensus_threshold": 2,
        "token_budget": 100.0, "timeout_ms": 60000,
    }])
    errors = validator._check_pop_tier(spec)
    assert any("consensus_threshold" in e.field for e in errors)


def test_tier_3_timeout_minimum(governance_db: Path):
    """Tier 3 requires timeout_ms >= 30000."""
    validator = ConstitutionalValidator(governance_db)
    spec = _make_spec([{
        "node_id": "A", "pop_tier": 3,
        "token_budget": 100.0, "timeout_ms": 10000,
    }])
    errors = validator._check_pop_tier(spec)
    assert len(errors) == 1
    assert "timeout_ms" in errors[0].field
    assert "30000" in errors[0].message
