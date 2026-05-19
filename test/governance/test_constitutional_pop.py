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


# ---------------------------------------------------------------------------
# Tier 3 PoP floor raised to 300_000 ms (5 min) — spec §1.5
# T1: exactly 5-minute timeout accepted
# ---------------------------------------------------------------------------

def test_tier3_exactly_5min_timeout_accepted(governance_db: Path):
    """T1: Tier 3 node with timeout_ms=300_000 must produce no timeout_ms errors."""
    validator = ConstitutionalValidator(governance_db)
    spec = _make_spec([{
        "node_id": "A", "pop_tier": 3,
        "token_budget": 100.0, "timeout_ms": 300_000,
    }])
    errors = validator._check_pop_tier(spec)
    timeout_errors = [e for e in errors if "timeout_ms" in e.field]
    assert timeout_errors == []


# T2: 299_999 ms rejected

def test_tier3_299999ms_rejected(governance_db: Path):
    """T2: Tier 3 node with timeout_ms=299_999 must produce exactly one timeout_ms error."""
    validator = ConstitutionalValidator(governance_db)
    spec = _make_spec([{
        "node_id": "A", "pop_tier": 3,
        "token_budget": 100.0, "timeout_ms": 299_999,
    }])
    errors = validator._check_pop_tier(spec)
    timeout_errors = [e for e in errors if "timeout_ms" in e.field]
    assert len(timeout_errors) == 1


# T3: old 30 s default rejected with spec §1.5 citation

def test_tier3_30000ms_rejected_cites_spec(governance_db: Path):
    """T3: Tier 3 node with timeout_ms=30_000 must be rejected and cite spec §1.5."""
    validator = ConstitutionalValidator(governance_db)
    spec = _make_spec([{
        "node_id": "A", "pop_tier": 3,
        "token_budget": 100.0, "timeout_ms": 30_000,
    }])
    errors = validator._check_pop_tier(spec)
    timeout_errors = [e for e in errors if "timeout_ms" in e.field]
    assert len(timeout_errors) == 1
    assert "§1.5" in timeout_errors[0].message


# T4: non-Tier-3 nodes unaffected

def test_tier1_30000ms_unaffected_by_tier3_floor(governance_db: Path):
    """T4a: Tier 1 node with timeout_ms=30_000 must not generate timeout_ms errors."""
    validator = ConstitutionalValidator(governance_db)
    spec = _make_spec([{
        "node_id": "A", "pop_tier": 1,
        "token_budget": 100.0, "timeout_ms": 30_000,
    }])
    errors = validator._check_pop_tier(spec)
    timeout_errors = [e for e in errors if "timeout_ms" in e.field]
    assert timeout_errors == []


def test_tier2_30000ms_unaffected_by_tier3_floor(governance_db: Path):
    """T4b: Tier 2 node with timeout_ms=30_000 must not generate timeout_ms errors."""
    validator = ConstitutionalValidator(governance_db)
    spec = _make_spec([{
        "node_id": "A", "pop_tier": 2,
        "redundancy_factor": 3, "consensus_threshold": 2,
        "token_budget": 100.0, "timeout_ms": 30_000,
    }])
    errors = validator._check_pop_tier(spec)
    timeout_errors = [e for e in errors if "timeout_ms" in e.field]
    assert timeout_errors == []


# Edge cases

def test_tier3_zero_timeout_caught_by_floor(governance_db: Path):
    """Edge: Tier 3 node with timeout_ms=0 must be caught (below any reasonable floor)."""
    validator = ConstitutionalValidator(governance_db)
    spec = _make_spec([{
        "node_id": "A", "pop_tier": 3,
        "token_budget": 100.0, "timeout_ms": 0,
    }])
    errors = validator._check_pop_tier(spec)
    timeout_errors = [e for e in errors if "timeout_ms" in e.field]
    assert len(timeout_errors) >= 1


def test_tier3_negative_timeout_caught_by_floor(governance_db: Path):
    """Edge: Tier 3 node with timeout_ms=-1 must be caught."""
    validator = ConstitutionalValidator(governance_db)
    spec = _make_spec([{
        "node_id": "A", "pop_tier": 3,
        "token_budget": 100.0, "timeout_ms": -1,
    }])
    errors = validator._check_pop_tier(spec)
    timeout_errors = [e for e in errors if "timeout_ms" in e.field]
    assert len(timeout_errors) >= 1


def test_mixed_tier_only_tier3_below_floor_reported(governance_db: Path):
    """Edge: Mixed DAG with one Tier 3 below floor and one Tier 1 at 30_000.

    Only the Tier 3 violation must be reported; Tier 1 is unaffected.
    """
    validator = ConstitutionalValidator(governance_db)
    spec = _make_spec([
        {"node_id": "T3-node", "pop_tier": 3, "token_budget": 100.0, "timeout_ms": 30_000},
        {"node_id": "T1-node", "pop_tier": 1, "token_budget": 100.0, "timeout_ms": 30_000},
    ])
    errors = validator._check_pop_tier(spec)
    timeout_errors = [e for e in errors if "timeout_ms" in e.field]
    assert len(timeout_errors) == 1
    assert "T3-node" in timeout_errors[0].message


def test_tier3_300001ms_accepted(governance_db: Path):
    """Edge: Tier 3 node with timeout_ms=300_001 must be accepted (off-by-one sanity)."""
    validator = ConstitutionalValidator(governance_db)
    spec = _make_spec([{
        "node_id": "A", "pop_tier": 3,
        "token_budget": 100.0, "timeout_ms": 300_001,
    }])
    errors = validator._check_pop_tier(spec)
    timeout_errors = [e for e in errors if "timeout_ms" in e.field]
    assert timeout_errors == []
