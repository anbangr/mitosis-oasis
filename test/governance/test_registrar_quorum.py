"""P6 — Test Registrar.check_quorum."""
import sqlite3
from pathlib import Path

from oasis.governance.clerks.registrar import Registrar
from oasis.governance.messages import IdentityAttestation


def _setup(governance_db: Path, num_producers: int = 3) -> Registrar:
    """Create session, register producers, and return Registrar."""
    reg = Registrar(str(governance_db), "did:oasis:clerk-registrar")
    reg.open_session("sess-q", min_reputation=0.1)

    conn = sqlite3.connect(str(governance_db))
    conn.execute("PRAGMA foreign_keys = ON")
    for i in range(1, num_producers + 1):
        conn.execute(
            "INSERT OR IGNORE INTO agent_registry "
            "(agent_did, agent_type, display_name, human_principal, reputation_score) "
            "VALUES (?, 'producer', ?, 'test@example.com', 0.5)",
            (f"did:mock:prod-{i}", f"Producer {i}"),
        )
    conn.commit()
    conn.close()
    return reg


def _attest(reg: Registrar, agent_did: str, agent_type: str = "producer"):
    """Submit an identity attestation for an agent."""
    att = IdentityAttestation(
        session_id="sess-q",
        agent_did=agent_did,
        signature="valid-sig",
        reputation_score=0.5,
        agent_type=agent_type,
    )
    reg.verify_identity(att)


def test_full_quorum_met(governance_db: Path):
    """Quorum is met when all required roles + enough producers are present."""
    reg = _setup(governance_db, num_producers=3)

    # Attest clerks (speaker, regulator, codifier)
    _attest(reg, "did:oasis:clerk-speaker", "clerk")
    _attest(reg, "did:oasis:clerk-regulator", "clerk")
    _attest(reg, "did:oasis:clerk-codifier", "clerk")

    # Attest 2 of 3 producers (> 51% threshold)
    _attest(reg, "did:mock:prod-1")
    _attest(reg, "did:mock:prod-2")

    assert reg.check_quorum("sess-q") is True


def test_missing_role_fails(governance_db: Path):
    """Quorum fails if a required clerk role is missing."""
    reg = _setup(governance_db, num_producers=3)

    # Only attest speaker + codifier (missing regulator)
    _attest(reg, "did:oasis:clerk-speaker", "clerk")
    _attest(reg, "did:oasis:clerk-codifier", "clerk")
    _attest(reg, "did:mock:prod-1")
    _attest(reg, "did:mock:prod-2")

    assert reg.check_quorum("sess-q") is False


def test_exactly_minimum(governance_db: Path):
    """Quorum passes with exactly the minimum required producers."""
    reg = _setup(governance_db, num_producers=2)

    _attest(reg, "did:oasis:clerk-speaker", "clerk")
    _attest(reg, "did:oasis:clerk-regulator", "clerk")
    _attest(reg, "did:oasis:clerk-codifier", "clerk")

    # quorum_threshold=0.51, 2 producers → need floor(0.51*2) = 1
    _attest(reg, "did:mock:prod-1")

    assert reg.check_quorum("sess-q") is True


def test_excess_agents_ok(governance_db: Path):
    """Extra agents beyond minimum don't break quorum check."""
    reg = _setup(governance_db, num_producers=5)

    _attest(reg, "did:oasis:clerk-speaker", "clerk")
    _attest(reg, "did:oasis:clerk-regulator", "clerk")
    _attest(reg, "did:oasis:clerk-codifier", "clerk")

    # All 5 producers
    for i in range(1, 6):
        _attest(reg, f"did:mock:prod-{i}")

    assert reg.check_quorum("sess-q") is True
