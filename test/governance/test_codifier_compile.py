"""P6 — Test Codifier.compile_spec."""
import sqlite3
from pathlib import Path

from oasis.governance.clerks.codifier import Codifier
from oasis.governance.messages import DAGProposal


def _setup(governance_db: Path) -> Codifier:
    """Create codifier with session."""
    conn = sqlite3.connect(str(governance_db))
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute(
        "INSERT OR IGNORE INTO legislative_session "
        "(session_id, state, epoch) VALUES ('sess-cod', 'CODIFICATION', 0)"
    )
    conn.execute(
        "INSERT OR IGNORE INTO agent_registry "
        "(agent_did, agent_type, display_name, human_principal, reputation_score) "
        "VALUES ('did:mock:proposer-1', 'producer', 'P1', 'test@example.com', 0.5)"
    )
    conn.commit()
    conn.close()
    return Codifier(str(governance_db), "did:oasis:clerk-codifier")


def _make_proposal() -> DAGProposal:
    return DAGProposal(
        session_id="sess-cod",
        proposer_did="did:mock:proposer-1",
        dag_spec={
            "nodes": [
                {"node_id": "root", "label": "Root", "service_id": "svc-a",
                 "pop_tier": 1, "token_budget": 100.0, "timeout_ms": 60000},
                {"node_id": "task-a", "label": "Task A", "service_id": "svc-b",
                 "pop_tier": 1, "token_budget": 50.0, "timeout_ms": 30000},
            ],
            "edges": [
                {"from_node_id": "root", "to_node_id": "task-a"},
            ],
        },
        rationale="Test proposal",
        token_budget_total=150.0,
        deadline_ms=60000,
    )


def _make_approved_bids() -> list[dict]:
    return [
        {
            "task_node_id": "root",
            "bidder_did": "did:mock:bidder-1",
            "service_id": "svc-a",
            "proposed_code_hash": "abcdef1234567890",
            "stake_amount": 1.0,
        },
        {
            "task_node_id": "task-a",
            "bidder_did": "did:mock:bidder-2",
            "service_id": "svc-b",
            "proposed_code_hash": "fedcba0987654321",
            "stake_amount": 1.0,
        },
    ]


def test_spec_compiled_from_proposal_and_bids(governance_db: Path):
    """compile_spec produces a valid MSG6 from proposal + bids."""
    cod = _setup(governance_db)
    proposal = _make_proposal()
    bids = _make_approved_bids()

    spec = cod.compile_spec("sess-cod", proposal, bids)
    assert spec.session_id == "sess-cod"
    assert spec.msg_type.value == "CODED_CONTRACT_SPEC"


def test_template_parameterization(governance_db: Path):
    """Compiled spec merges node info with bid info."""
    cod = _setup(governance_db)
    proposal = _make_proposal()
    bids = _make_approved_bids()

    spec = cod.compile_spec("sess-cod", proposal, bids)
    assignments = spec.service_contract_specs.get("service_assignments", [])
    assert len(assignments) == 2
    assert assignments[0]["node_id"] == "root"
    assert assignments[0]["bidder_did"] == "did:mock:bidder-1"


def test_all_fields_populated(governance_db: Path):
    """All 5 module specs are populated in the compiled spec."""
    cod = _setup(governance_db)
    proposal = _make_proposal()
    bids = _make_approved_bids()

    spec = cod.compile_spec("sess-cod", proposal, bids)
    assert spec.collaboration_contract_spec is not None
    assert spec.guardian_module_spec is not None
    assert spec.verification_module_spec is not None
    assert spec.gate_module_spec is not None
    assert spec.service_contract_specs is not None
    assert spec.validation_proof is not None
