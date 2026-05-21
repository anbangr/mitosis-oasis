"""EIP-712 signature verification for binding write routes.

The OASIS API uses a split authentication model:

* **Session auth** (cookie / API-key) — protects the Logging Hub, Dashboard,
  and all observation reads.  These routes are stateful and user-facing.
* **EIP-712 typed-data signatures** — protects *binding* write routes such as
  adjudication sanctions (slash / freeze) and constitution amendments.
  Clients sign the canonical JSON payload off-line; the server verifies the
  signature against the request body verbatim.

This module provides ``require_eip712_sig``, a FastAPI dependency that performs
the server-side half of the handshake.
"""

from __future__ import annotations

from fastapi import HTTPException, Request

from oasis.crypto.eip712 import verify
from oasis.crypto.typed_data import DOMAIN


def _extract_eip712_message(
    primary_type: str, body: dict[str, object]
) -> dict[str, object]:
    r"""Project the EIP-712 message out of the request body.

    For Sanction / ConstitutionAmendment, the message is the body verbatim
    (legacy contract). For Impeachment, the body contains an additional
    `signatures` envelope field that is NOT part of the typed-data
    message; project only the three typed fields.
    """
    if primary_type == "Impeachment":
        return {
            "target_did": body["target_did"],
            "evidence_cid": body["evidence_cid"],
            "motion_id": body["motion_id"],
        }
    return body


def _route_to_primary_type(method: str, path: str) -> str | None:
    r"""Map an HTTP route to its EIP-712 primary_type.

    Returns ``None`` for unmapped routes (defensive — a dependency wired on
    an unmapped route would raise 500).
    """
    _map = {
        ("POST", "/api/adjudication/slash"): "Sanction",
        ("POST", "/api/v1/adjudication/slash"): "Sanction",
        ("POST", "/api/adjudication/freeze"): "Sanction",
        ("POST", "/api/v1/adjudication/freeze"): "Sanction",
        ("POST", "/api/adjudication/override"): "Sanction",
        ("POST", "/api/v1/adjudication/override"): "Sanction",
        ("POST", "/api/adjudication/impeach"): "Impeachment",
        ("POST", "/api/v1/adjudication/impeach"): "Impeachment",
        ("PUT", "/api/governance/constitution"): "ConstitutionAmendment",
        ("PUT", "/api/v1/governance/constitution"): "ConstitutionAmendment",
    }
    return _map.get((method, path))


async def require_eip712_sig(request: Request) -> str:
    r"""FastAPI dependency — verify the request carries a valid EIP-712 signature.

    Reads ``X-EIP712-Signature`` and ``X-EIP712-Signer`` headers, hex-decodes
    the signature, looks up the route's ``primary_type``, and calls
    :func:`oasis.crypto.eip712.verify` with the request body passed **verbatim**.

    Raises
    ------
    HTTPException(401)
        If either header is missing or signature verification fails.
    HTTPException(400)
        If the signature is not valid hex.
    HTTPException(500)
        If the route is not present in the binding-write map (programmer error).
    """
    sig_hex = request.headers.get("X-EIP712-Signature")
    signer = request.headers.get("X-EIP712-Signer")

    if not sig_hex or not signer:
        raise HTTPException(
            status_code=401,
            detail="EIP-712 signature required (X-EIP712-Signature / X-EIP712-Signer)",
        )

    # Accept optional 0x prefix
    if sig_hex.startswith("0x") or sig_hex.startswith("0X"):
        sig_hex = sig_hex[2:]

    try:
        signature = bytes.fromhex(sig_hex)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid hex signature")

    primary_type = _route_to_primary_type(request.method, request.url.path)
    if primary_type is None:
        raise HTTPException(
            status_code=500,
            detail="Route not mapped for EIP-712 authentication",
        )

    body = await request.json()
    typed_message = _extract_eip712_message(primary_type, body)

    if not verify(
        domain=DOMAIN,
        primary_type=primary_type,
        message=typed_message,
        signature=signature,
        expected_signer=signer,
    ):
        raise HTTPException(
            status_code=401,
            detail="EIP-712 signature verification failed",
        )

    return signer
