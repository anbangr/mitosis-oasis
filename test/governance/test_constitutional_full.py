"""Tests for full constitutional validation (all 6 checks)."""
import sqlite3
from pathlib import Path

from oasis.governance.constitutional import ConstitutionalValidator
from oasis.governance.messages import CodedContractSpec


def _register_agent(db_path: Path, agent_did: str, reputation: float = 0.5):
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute(
        "INSERT OR IGNORE INTO agent_registry "
        "(agent_did, agent_type, display_name, reputation_score) "
        "VALUES (?, 'producer', ?, ?)",
        (agent_did, f"Agent {agent_did}", reputation),
    )
    conn.commit()
    conn.close()


def _valid_spec(bid_assignments: dict | None = None) -> CodedContractSpec:
    """Build a fully valid CodedContractSpec."""
    ba = bid_assignments or {}
    return CodedContractSpec(
        session_id="sess-1",
        collaboration_contract_spec={
            "deviation_sigma": 3.0,
            "max_tools": 50,
            "max_messages": 100,
            "escalation_freeze_rounds": 5,
        },
        guardian_module_spec={"mode": "passive"},
        verification_module_spec={"type": "hash"},
        gate_module_spec={"threshold": 0.5},
        service_contract_specs={
            "dag_spec": {
                "nodes": [
                    {"node_id": "root", "label": "Root", "service_id": "svc",
                     "pop_tier": 1, "token_budget": 500.0, "timeout_ms": 60000},
                    {"node_id": "task-a", "label": "Task A", "service_id": "svc-a",
                     "pop_tier": 1, "token_budget": 200.0, "timeout_ms": 60000},
                    {"node_id": "task-b", "label": "Task B", "service_id": "svc-b",
                     "pop_tier": 1, "token_budget": 200.0, "timeout_ms": 60000},
                ],
                "edges": [
                    {"from_node_id": "root", "to_node_id": "task-a"},
                    {"from_node_id": "root", "to_node_id": "task-b"},
                ],
            },
            "bid_assignments": ba,
        },
        validation_proof="proof-abc",
    )


def test_full_validation_passes(governance_db: Path):
    """A fully valid spec passes all 6 checks."""
    _register_agent(governance_db, "did:test:a1", 0.5)
    _register_agent(governance_db, "did:test:a2", 0.5)
    validator = ConstitutionalValidator(governance_db)
    spec = _valid_spec({"did:test:a1": 0.5, "did:test:a2": 0.5})
    result = validator.validate(spec)
    assert result.passed, [e.message for e in result.errors]


def test_multiple_failures_aggregated(governance_db: Path):
    """Multiple failures across checks are all reported."""
    validator = ConstitutionalValidator(governance_db)
    spec = CodedContractSpec(
        session_id="sess-1",
        collaboration_contract_spec={
            "deviation_sigma": 0.1,   # out of range
            "max_tools": 1000,        # out of range
        },
        guardian_module_spec={"mode": "passive"},
        verification_module_spec={"type": "hash"},
        gate_module_spec={"threshold": 0.5},
        service_contract_specs={
            "dag_spec": {
                "nodes": [
                    {"node_id": "A", "pop_tier": 1,
                     "token_budget": -5.0, "timeout_ms": 60000},
                ],
                "edges": [],
            },
            "bid_assignments": {"did:test:unknown": 1.0},
        },
        validation_proof="proof-abc",
    )
    result = validator.validate(spec)
    assert not result.passed
    checks_hit = {e.check for e in result.errors}
    # Should have at least behavioral and budget and identity errors
    assert "behavioral_params" in checks_hit
    assert "budget_compliance" in checks_hit
    assert "identity_stake" in checks_hit


def test_partial_failures_reported(governance_db: Path):
    """Failures in some checks don't prevent other checks from running."""
    _register_agent(governance_db, "did:test:a1", 0.5)
    validator = ConstitutionalValidator(governance_db)
    # Valid behavioral, invalid budget (negative)
    spec = CodedContractSpec(
        session_id="sess-1",
        collaboration_contract_spec={"deviation_sigma": 3.0},
        guardian_module_spec={"mode": "passive"},
        verification_module_spec={"type": "hash"},
        gate_module_spec={"threshold": 0.5},
        service_contract_specs={
            "dag_spec": {
                "nodes": [
                    {"node_id": "A", "pop_tier": 1,
                     "token_budget": -10.0, "timeout_ms": 60000},
                ],
                "edges": [],
            },
            "bid_assignments": {"did:test:a1": 1.0},
        },
        validation_proof="proof-abc",
    )
    result = validator.validate(spec)
    assert not result.passed
    # Budget should fail, behavioral should pass
    checks = {e.check for e in result.errors}
    assert "budget_compliance" in checks
    assert "behavioral_params" not in checks
