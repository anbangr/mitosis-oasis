"""P6 — Test Registrar.check_quorum."""

from __future__ import annotations

from pathlib import Path

from oasis.crypto import ed25519
from oasis.crypto.did import did_from_pubkey
from oasis.governance.clerks.registrar import Registrar
from oasis.governance.messages import IdentityAttestation, canonical_signed_bytes
from oasis.governance.schema import get_clerk_keypair


def _setup(
    governance_db: Path, num_producers: int = 3
) -> tuple[Registrar, dict[str, bytes]]:
    """Create session, register producers with real keys, and return (Registrar, priv_key_map)."""
    reg = Registrar(
        str(governance_db), "did:key:z6Mkkwz2P6pxvfqPxgdssMRZ9UNThiuMueGdV4awUacowDLd"
    )
    reg.open_session("sess-q", min_reputation=0.1)

    priv_map: dict[str, bytes] = {}
    for i in range(1, num_producers + 1):
        priv, pub = ed25519.generate_keypair()
        agent_did = did_from_pubkey(pub)
        reg.register_agent(
            agent_did,
            "producer",
            f"Producer {i}",
            public_key=pub.hex(),
        )
        priv_map[agent_did] = priv

    return reg, priv_map


def _attest(
    reg: Registrar, agent_did: str, private_key: bytes, agent_type: str = "producer"
):
    """Submit a real Ed25519-signed identity attestation for an agent."""
    att = IdentityAttestation(
        session_id="sess-q",
        agent_did=agent_did,
        signature="ab" * 64,
        reputation_score=0.5,
        agent_type=agent_type,
    )
    canonical = canonical_signed_bytes(att)
    sig = ed25519.sign(private_key, canonical)
    att.signature = sig.hex()
    result = reg.verify_identity(att)
    assert result["passed"], f"Attestation failed for {agent_did}: {result['errors']}"


def test_full_quorum_met(governance_db: Path):
    """Quorum is met when all required roles + enough producers are present."""
    reg, priv_map = _setup(governance_db, num_producers=3)

    # Attest clerks (speaker, regulator, codifier)
    for role in ("speaker", "regulator", "codifier"):
        priv, _pub, did = get_clerk_keypair(role)
        _attest(reg, did, priv, "clerk")

    # Attest 2 of 3 producers (> 51% threshold)
    producer_dids = list(priv_map.keys())
    _attest(reg, producer_dids[0], priv_map[producer_dids[0]])
    _attest(reg, producer_dids[1], priv_map[producer_dids[1]])

    assert reg.check_quorum("sess-q") is True


def test_missing_role_fails(governance_db: Path):
    """Quorum fails if a required clerk role is missing."""
    reg, priv_map = _setup(governance_db, num_producers=3)

    # Only attest speaker + codifier (missing regulator)
    priv_s, _pub_s, did_s = get_clerk_keypair("speaker")
    priv_c, _pub_c, did_c = get_clerk_keypair("codifier")
    _attest(reg, did_s, priv_s, "clerk")
    _attest(reg, did_c, priv_c, "clerk")

    producer_dids = list(priv_map.keys())
    _attest(reg, producer_dids[0], priv_map[producer_dids[0]])
    _attest(reg, producer_dids[1], priv_map[producer_dids[1]])

    assert reg.check_quorum("sess-q") is False


def test_exactly_minimum(governance_db: Path):
    """Quorum passes with exactly the minimum required producers."""
    reg, priv_map = _setup(governance_db, num_producers=2)

    for role in ("speaker", "regulator", "codifier"):
        priv, _pub, did = get_clerk_keypair(role)
        _attest(reg, did, priv, "clerk")

    producer_dids = list(priv_map.keys())
    _attest(reg, producer_dids[0], priv_map[producer_dids[0]])
    _attest(reg, producer_dids[1], priv_map[producer_dids[1]])

    assert reg.check_quorum("sess-q") is True


def test_excess_agents_ok(governance_db: Path):
    """Extra agents beyond minimum don't break quorum check."""
    reg, priv_map = _setup(governance_db, num_producers=5)

    for role in ("speaker", "regulator", "codifier"):
        priv, _pub, did = get_clerk_keypair(role)
        _attest(reg, did, priv, "clerk")

    for agent_did, priv in priv_map.items():
        _attest(reg, agent_did, priv)

    assert reg.check_quorum("sess-q") is True
