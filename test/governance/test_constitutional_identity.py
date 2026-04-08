"""Tests for constitutional identity/stake validation."""
import sqlite3
from pathlib import Path

from oasis.governance.constitutional import ConstitutionalValidator
from oasis.governance.messages import CodedContractSpec


def _make_spec(bid_assignments: dict) -> CodedContractSpec:
    """Build a CodedContractSpec with given bid assignments."""
    return CodedContractSpec(
        session_id="sess-1",
        collaboration_contract_spec={},
        guardian_module_spec={"mode": "passive"},
        verification_module_spec={"type": "hash"},
        gate_module_spec={"threshold": 0.5},
        service_contract_specs={
            "dag_spec": {"nodes": [], "edges": []},
            "bid_assignments": bid_assignments,
        },
        validation_proof="proof-abc",
    )


def _register_agent(db_path: Path, agent_did: str, reputation: float = 0.5):
    """Insert a producer agent into the registry."""
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


def test_all_agents_meet_floor(governance_db: Path):
    """All agents registered with reputation above floor pass."""
    _register_agent(governance_db, "did:test:a1", 0.5)
    _register_agent(governance_db, "did:test:a2", 0.8)
    validator = ConstitutionalValidator(governance_db)
    spec = _make_spec({"did:test:a1": 0.5, "did:test:a2": 0.5})
    errors = validator._check_identity_stake(spec)
    assert errors == []


def test_one_below_floor(governance_db: Path):
    """An agent below the reputation floor should fail."""
    _register_agent(governance_db, "did:test:a1", 0.05)  # below 0.1 floor
    validator = ConstitutionalValidator(governance_db)
    spec = _make_spec({"did:test:a1": 1.0})
    errors = validator._check_identity_stake(spec)
    assert len(errors) == 1
    assert "below floor" in errors[0].message.lower()


def test_unregistered_agent(governance_db: Path):
    """An agent not in the registry should fail."""
    validator = ConstitutionalValidator(governance_db)
    spec = _make_spec({"did:test:unknown": 1.0})
    errors = validator._check_identity_stake(spec)
    assert len(errors) == 1
    assert "not registered" in errors[0].message.lower()
