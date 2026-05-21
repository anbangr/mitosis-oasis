"""T1–T9 — require_eip712_sig middleware + binding route auth (Phase 1).

These tests import ``require_eip712_sig`` and ``_route_to_primary_type``
from the *not-yet-implemented* module ``oasis.api_auth``.  They will fail
at import time or runtime during the Red phase, then pass once the
middleware is written.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from eth_account import Account
from fastapi.testclient import TestClient

from oasis.api import app
from oasis.crypto.eip712 import sign
from oasis.crypto.typed_data import DOMAIN


# ---------------------------------------------------------------------------
# Lazy import fixtures (so collection succeeds during Red phase)
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def require_eip712_sig():
    from oasis.api_auth import require_eip712_sig as dep

    return dep


@pytest.fixture(scope="module")
def _route_to_primary_type():
    from oasis.api_auth import _route_to_primary_type as fn

    return fn


@pytest.fixture
def acct():
    return Account.create()


@pytest.fixture
def auth_client(tmp_path: Path) -> TestClient:
    r"""TestClient with governance + adjudication databases initialised."""
    from oasis.adjudication import endpoints as adj_ep
    from oasis.adjudication.schema import create_adjudication_tables
    from oasis.governance import endpoints as gov_ep
    from oasis.governance.schema import (
        create_governance_tables,
        seed_clerks,
        seed_constitution,
    )

    gov_db = tmp_path / "auth_gov.db"
    create_governance_tables(gov_db)
    seed_constitution(gov_db)
    seed_clerks(gov_db)
    gov_ep.init_governance_db(str(gov_db))

    adj_db = tmp_path / "auth_adj.db"
    create_adjudication_tables(adj_db)
    adj_ep.init_adjudication_db(str(adj_db))

    return TestClient(app, raise_server_exceptions=False)


def _seed_acct_as_adjudicator(acct) -> None:
    r"""Register *acct* in the active adjudication DB's adjudicator_registry.

    Bundle-2 wires ``/slash``, ``/freeze``, and ``/override`` behind
    ``_resolve_adjudicator_did_from_signer``; the Bundle-1 EIP-712 tests
    therefore need to plant the signer's eth address before they can prove
    valid signatures are accepted (the resolver returns ``None`` otherwise
    and the endpoint short-circuits to HTTP 401).
    """
    import sqlite3

    from oasis.adjudication import endpoints as adj_ep

    conn = sqlite3.connect(adj_ep._get_db())
    try:
        conn.execute(
            "INSERT OR IGNORE INTO adjudicator_registry "
            "(adjudicator_did, eth_address) VALUES (?, ?)",
            (f"did:adj:{acct.address.lower()}", acct.address),
        )
        conn.commit()
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# T1 — slash without headers → 401
# ---------------------------------------------------------------------------


def test_t1_slash_without_headers(auth_client):
    r"""POST /api/adjudication/slash without EIP-712 headers returns 401."""
    resp = auth_client.post(
        "/api/adjudication/slash",
        json={
            "target_did": "did:key:zVictim",
            "amount_wei": 100,
            "reason": "test",
            "nonce": 1,
        },
    )
    assert resp.status_code == 401
    assert "EIP-712" in resp.text or "signature" in resp.text.lower()


# ---------------------------------------------------------------------------
# T2 — slash with valid EIP-712 → not 401
# ---------------------------------------------------------------------------


def test_t2_slash_with_valid_eip712(auth_client, acct):
    r"""POST /api/adjudication/slash with valid EIP-712 headers is accepted."""
    _seed_acct_as_adjudicator(acct)
    body = {
        "target_did": "did:key:zVictim",
        "amount_wei": 100,
        "reason": "test",
        "nonce": 1,
    }
    sig = sign(acct.key, DOMAIN, "Sanction", body)
    resp = auth_client.post(
        "/api/adjudication/slash",
        json=body,
        headers={
            "X-EIP712-Signature": sig.hex(),
            "X-EIP712-Signer": acct.address,
        },
    )
    # 404 is acceptable if the target agent is not yet registered.
    assert resp.status_code != 401
    # Distinguish FastAPI's generic "Not Found" (endpoint missing in Red
    # phase) from an application-level 404 returned by the endpoint.
    if resp.status_code == 404:
        assert resp.json() != {"detail": "Not Found"}


# ---------------------------------------------------------------------------
# T3 — slash body mismatch with signed payload → 401
# ---------------------------------------------------------------------------


def test_t3_slash_body_mismatch(auth_client, acct):
    r"""Tampering the request body after signing causes 401."""
    signed_body = {
        "target_did": "did:key:zVictim",
        "amount_wei": 100,
        "reason": "test",
        "nonce": 1,
    }
    tampered_body = {
        "target_did": "did:key:zVictim",
        "amount_wei": 200,
        "reason": "test",
        "nonce": 1,
    }
    sig = sign(acct.key, DOMAIN, "Sanction", signed_body)
    resp = auth_client.post(
        "/api/adjudication/slash",
        json=tampered_body,
        headers={
            "X-EIP712-Signature": sig.hex(),
            "X-EIP712-Signer": acct.address,
        },
    )
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# T4 — constitution PUT without headers → 401
# ---------------------------------------------------------------------------


def test_t4_constitution_put_without_headers(auth_client):
    r"""PUT /api/governance/constitution without EIP-712 headers returns 401."""
    resp = auth_client.put(
        "/api/governance/constitution",
        json={
            "param_name": "reputation_lambda",
            "param_value": "0.7",
            "nonce": 1,
        },
    )
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# T5–T7 — read-only routes are unprotected
# ---------------------------------------------------------------------------


def test_t5_treasury_read_not_401(auth_client, _route_to_primary_type):
    r"""GET /api/adjudication/treasury does not require EIP-712 auth."""
    # Defensive: read-only routes must not appear in the binding-write map.
    assert _route_to_primary_type("GET", "/api/adjudication/treasury") is None

    resp = auth_client.get("/api/adjudication/treasury")
    assert resp.status_code != 401


def test_t6_decisions_read_not_401(auth_client, _route_to_primary_type):
    r"""GET /api/adjudication/decisions does not require EIP-712 auth."""
    assert _route_to_primary_type("GET", "/api/adjudication/decisions") is None

    resp = auth_client.get("/api/adjudication/decisions")
    assert resp.status_code != 401


def test_t7_alerts_read_not_401(auth_client, _route_to_primary_type):
    r"""GET /api/adjudication/alerts does not require EIP-712 auth."""
    assert _route_to_primary_type("GET", "/api/adjudication/alerts") is None

    resp = auth_client.get("/api/adjudication/alerts")
    assert resp.status_code != 401


# ---------------------------------------------------------------------------
# T8 — bad-hex signature → 400
# ---------------------------------------------------------------------------


def test_t8_bad_hex_signature(auth_client):
    r"""A malformed hex signature produces 400 with 'hex' in the body."""
    resp = auth_client.post(
        "/api/adjudication/slash",
        json={
            "target_did": "did:key:zVictim",
            "amount_wei": 100,
            "reason": "test",
            "nonce": 1,
        },
        headers={
            "X-EIP712-Signature": "notHex!!!",
            "X-EIP712-Signer": "0x" + "00" * 20,
        },
    )
    assert resp.status_code == 400
    assert "hex" in resp.text.lower()


# ---------------------------------------------------------------------------
# T9 — unmapped route returns None
# ---------------------------------------------------------------------------


def test_t9_unmapped_route_returns_none(_route_to_primary_type):
    r"""_route_to_primary_type returns None for unknown routes."""
    result = _route_to_primary_type("POST", "/totally-other")
    assert result is None


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


def test_edge_signature_with_0x_prefix(auth_client, acct):
    r"""X-EIP712-Signature may include an optional 0x prefix."""
    _seed_acct_as_adjudicator(acct)
    body = {
        "target_did": "did:key:zVictim",
        "amount_wei": 100,
        "reason": "test",
        "nonce": 1,
    }
    sig = sign(acct.key, DOMAIN, "Sanction", body)
    resp = auth_client.post(
        "/api/adjudication/slash",
        json=body,
        headers={
            "X-EIP712-Signature": "0x" + sig.hex(),
            "X-EIP712-Signer": acct.address,
        },
    )
    assert resp.status_code != 401
    if resp.status_code == 404:
        assert resp.json() != {"detail": "Not Found"}


def test_edge_signer_case_insensitive(auth_client, acct):
    r"""Recovered signer is compared case-insensitively to X-EIP712-Signer."""
    _seed_acct_as_adjudicator(acct)
    body = {
        "target_did": "did:key:zVictim",
        "amount_wei": 100,
        "reason": "test",
        "nonce": 1,
    }
    sig = sign(acct.key, DOMAIN, "Sanction", body)
    # Send signer address in lowercase
    resp = auth_client.post(
        "/api/adjudication/slash",
        json=body,
        headers={
            "X-EIP712-Signature": sig.hex(),
            "X-EIP712-Signer": acct.address.lower(),
        },
    )
    assert resp.status_code != 401
    if resp.status_code == 404:
        assert resp.json() != {"detail": "Not Found"}


def test_edge_middleware_passes_body_verbatim(auth_client, acct):
    r"""The middleware must pass the request body verbatim to eip712.verify.

    Changing a field name (e.g. ``amount_wei`` → ``amount``) breaks the
    signature because the typed-data schema expects ``amount_wei``.
    """
    canonical_body = {
        "target_did": "did:key:zVictim",
        "amount_wei": 100,
        "reason": "test",
        "nonce": 1,
    }
    # Client mistakenly sends ``amount`` instead of ``amount_wei``
    wrong_body = {
        "target_did": "did:key:zVictim",
        "amount": 100,
        "reason": "test",
        "nonce": 1,
    }
    sig = sign(acct.key, DOMAIN, "Sanction", canonical_body)
    resp = auth_client.post(
        "/api/adjudication/slash",
        json=wrong_body,
        headers={
            "X-EIP712-Signature": sig.hex(),
            "X-EIP712-Signer": acct.address,
        },
    )
    assert resp.status_code == 401


def test_edge_freeze_without_headers_401(auth_client):
    r"""POST /api/adjudication/freeze without EIP-712 headers returns 401."""
    resp = auth_client.post(
        "/api/adjudication/freeze",
        json={
            "target_did": "did:key:zVictim",
            "amount_wei": 0,
            "reason": "test",
            "nonce": 1,
        },
    )
    assert resp.status_code == 401
    assert "EIP-712" in resp.text or "signature" in resp.text.lower()


def test_edge_v1_slash_without_headers_401(auth_client):
    r"""POST /api/v1/adjudication/slash is also protected."""
    resp = auth_client.post(
        "/api/v1/adjudication/slash",
        json={
            "target_did": "did:key:zVictim",
            "amount_wei": 100,
            "reason": "test",
            "nonce": 1,
        },
    )
    assert resp.status_code == 401
