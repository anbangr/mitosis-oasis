"""P6 — Test Speaker.receive_proposal."""

import sqlite3
from pathlib import Path

from oasis.crypto import ed25519
from oasis.crypto.did import did_from_pubkey
from oasis.governance.clerks.speaker import Speaker
from oasis.governance.messages import DAGProposal, canonical_signed_bytes


def _make_speaker(governance_db: Path) -> Speaker:
    """Create a Speaker clerk with a session."""
    sp = Speaker(
        str(governance_db), "did:key:z6Mknpo1FQJ19grCZsqJcsRBBKegBS8EQ8H6pk6hxiFtoWSK"
    )
    conn = sqlite3.connect(str(governance_db))
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute(
        "INSERT OR IGNORE INTO legislative_session "
        "(session_id, state, epoch) VALUES ('sess-sp', 'PROPOSAL_OPEN', 0)"
    )
    conn.commit()
    conn.close()
    return sp


def _register_proposer(governance_db: Path) -> tuple[str, bytes]:
    """Register a producer agent with a real Ed25519 keypair."""
    priv, pub = ed25519.generate_keypair()
    did = did_from_pubkey(pub)
    conn = sqlite3.connect(str(governance_db))
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute(
        "INSERT OR IGNORE INTO agent_registry "
        "(agent_did, agent_type, display_name, human_principal, reputation_score, public_key) "
        "VALUES (?, 'producer', 'Proposer', 'test@example.com', 0.5, ?)",
        (did, pub.hex()),
    )
    conn.commit()
    conn.close()
    return did, priv


def _sign_proposal(proposal: DAGProposal, private_key: bytes) -> DAGProposal:
    """Sign a DAGProposal with the proposer's Ed25519 private key."""
    canonical = canonical_signed_bytes(proposal)
    proposal.signature = ed25519.sign(private_key, canonical).hex()
    return proposal


def _valid_dag() -> dict:
    return {
        "nodes": [
            {
                "node_id": "root",
                "label": "Root",
                "service_id": "svc-a",
                "pop_tier": 1,
                "token_budget": 100.0,
                "timeout_ms": 60000,
            },
            {
                "node_id": "task-a",
                "label": "Task A",
                "service_id": "svc-b",
                "pop_tier": 1,
                "token_budget": 50.0,
                "timeout_ms": 30000,
            },
        ],
        "edges": [
            {"from_node_id": "root", "to_node_id": "task-a"},
        ],
    }


def test_valid_proposal_accepted(governance_db: Path):
    """Valid proposal with acyclic DAG and within budget passes."""
    sp = _make_speaker(governance_db)
    proposer_did, proposer_priv = _register_proposer(governance_db)
    proposal = DAGProposal(
        session_id="sess-sp",
        proposer_did=proposer_did,
        dag_spec=_valid_dag(),
        rationale="Test proposal",
        token_budget_total=500.0,
        deadline_ms=60000,
    )
    _sign_proposal(proposal, proposer_priv)
    result = sp.receive_proposal("sess-sp", proposal)
    assert result["passed"] is True
    assert result["proposal_id"] is not None
    assert len(result["topological_order"]) == 2


def test_cyclic_dag_rejected(governance_db: Path):
    """Proposal with cyclic DAG is rejected."""
    sp = _make_speaker(governance_db)
    proposer_did, proposer_priv = _register_proposer(governance_db)
    cyclic_dag = {
        "nodes": [
            {
                "node_id": "a",
                "label": "A",
                "service_id": "svc",
                "pop_tier": 1,
                "token_budget": 100.0,
                "timeout_ms": 60000,
            },
            {
                "node_id": "b",
                "label": "B",
                "service_id": "svc",
                "pop_tier": 1,
                "token_budget": 100.0,
                "timeout_ms": 60000,
            },
        ],
        "edges": [
            {"from_node_id": "a", "to_node_id": "b"},
            {"from_node_id": "b", "to_node_id": "a"},
        ],
    }
    proposal = DAGProposal(
        session_id="sess-sp",
        proposer_did=proposer_did,
        dag_spec=cyclic_dag,
        rationale="Cyclic test",
        token_budget_total=200.0,
        deadline_ms=60000,
    )
    _sign_proposal(proposal, proposer_priv)
    result = sp.receive_proposal("sess-sp", proposal)
    assert result["passed"] is False
    assert any("cycle" in e.lower() for e in result["errors"])


def test_budget_exceeded_rejected(governance_db: Path):
    """Proposal exceeding budget cap is rejected."""
    sp = _make_speaker(governance_db)
    proposer_did, proposer_priv = _register_proposer(governance_db)
    proposal = DAGProposal(
        session_id="sess-sp",
        proposer_did=proposer_did,
        dag_spec=_valid_dag(),
        rationale="Expensive test",
        token_budget_total=2_000_000.0,  # Exceeds 1M cap
        deadline_ms=60000,
    )
    _sign_proposal(proposal, proposer_priv)
    result = sp.receive_proposal("sess-sp", proposal)
    assert result["passed"] is False
    assert any("budget" in e.lower() or "cap" in e.lower() for e in result["errors"])


def test_deadline_exceeded_rejected(governance_db: Path):
    """Proposal with deadline exceeding max is rejected."""
    sp = _make_speaker(governance_db)
    proposer_did, proposer_priv = _register_proposer(governance_db)
    proposal = DAGProposal(
        session_id="sess-sp",
        proposer_did=proposer_did,
        dag_spec=_valid_dag(),
        rationale="Late test",
        token_budget_total=500.0,
        deadline_ms=100_000_000,  # Exceeds 86.4M max
    )
    _sign_proposal(proposal, proposer_priv)
    result = sp.receive_proposal("sess-sp", proposal)
    assert result["passed"] is False
    assert any("deadline" in e.lower() or "max" in e.lower() for e in result["errors"])
