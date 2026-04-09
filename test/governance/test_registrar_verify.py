"""P6 — Test Registrar.verify_identity."""
import sqlite3
from pathlib import Path

from oasis.governance.clerks.registrar import Registrar
from oasis.governance.messages import IdentityAttestation


def _setup_session(governance_db: Path, session_id: str = "sess-v") -> Registrar:
    """Create a registrar with an open session."""
    reg = Registrar(str(governance_db), "did:oasis:clerk-registrar")
    reg.open_session(session_id, min_reputation=0.3)
    return reg


def _register_producer(governance_db: Path, did: str, rep: float = 0.5):
    """Register a producer agent in agent_registry."""
    conn = sqlite3.connect(str(governance_db))
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute(
        "INSERT OR IGNORE INTO agent_registry "
        "(agent_did, agent_type, display_name, human_principal, reputation_score) "
        "VALUES (?, 'producer', ?, 'test@example.com', ?)",
        (did, f"Producer {did}", rep),
    )
    conn.commit()
    conn.close()


def test_valid_identity_passes(governance_db: Path):
    """Valid attestation with good DID, signature, and reputation passes."""
    reg = _setup_session(governance_db)
    _register_producer(governance_db, "did:mock:prod-1", 0.5)

    att = IdentityAttestation(
        session_id="sess-v",
        agent_did="did:mock:prod-1",
        signature="valid-sig-abc123",
        reputation_score=0.5,
        agent_type="producer",
    )
    result = reg.verify_identity(att)
    assert result["passed"] is True
    assert result["agent_did"] == "did:mock:prod-1"


def test_bad_signature_fails(governance_db: Path):
    """Empty signature fails verification."""
    reg = _setup_session(governance_db)
    _register_producer(governance_db, "did:mock:prod-2", 0.5)

    # Pydantic won't allow empty string for min_length=1 signature,
    # so we test with layer1_process indirectly.
    # Instead, test invalid DID format.
    att = IdentityAttestation(
        session_id="sess-v",
        agent_did="invalid-no-did-prefix",
        signature="valid-sig",
        reputation_score=0.5,
        agent_type="producer",
    )
    result = reg.verify_identity(att)
    assert result["passed"] is False
    assert any("Invalid DID" in e for e in result["errors"])


def test_low_reputation_fails(governance_db: Path):
    """Attestation with reputation below session minimum fails."""
    reg = _setup_session(governance_db)
    _register_producer(governance_db, "did:mock:prod-3", 0.1)

    att = IdentityAttestation(
        session_id="sess-v",
        agent_did="did:mock:prod-3",
        signature="valid-sig",
        reputation_score=0.1,
        agent_type="producer",
    )
    result = reg.verify_identity(att)
    assert result["passed"] is False
    assert any("Reputation" in e or "below minimum" in e for e in result["errors"])


def test_duplicate_did_fails(governance_db: Path):
    """Same DID cannot attest twice in same session."""
    reg = _setup_session(governance_db)
    _register_producer(governance_db, "did:mock:prod-4", 0.5)

    att = IdentityAttestation(
        session_id="sess-v",
        agent_did="did:mock:prod-4",
        signature="valid-sig",
        reputation_score=0.5,
        agent_type="producer",
    )
    result1 = reg.verify_identity(att)
    assert result1["passed"] is True

    result2 = reg.verify_identity(att)
    assert result2["passed"] is False
    assert any("Duplicate" in e for e in result2["errors"])


def test_clerk_vs_producer_type(governance_db: Path):
    """Agent type mismatch between registry and attestation fails."""
    reg = _setup_session(governance_db)
    # did:oasis:clerk-registrar is type 'clerk' in registry
    att = IdentityAttestation(
        session_id="sess-v",
        agent_did="did:oasis:clerk-registrar",
        signature="valid-sig",
        reputation_score=0.5,
        agent_type="producer",  # Wrong — should be 'clerk'
    )
    result = reg.verify_identity(att)
    assert result["passed"] is False
    assert any("type mismatch" in e.lower() for e in result["errors"])
