"""P8.9 — Approval & deployment API tests."""
from __future__ import annotations

import sqlite3


def test_dual_sign_off(client, session_factory, gov_db):
    """POST approval with dual signatures transitions to DEPLOYED."""
    session_id = session_factory("AWAITING_APPROVAL")

    # Get spec_id
    conn = sqlite3.connect(str(gov_db))
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        "SELECT spec_id FROM contract_spec WHERE session_id = ? AND status = 'validated'",
        (session_id,),
    ).fetchone()
    conn.close()
    assert row is not None, "No validated spec found"

    resp = client.post(
        f"/api/governance/sessions/{session_id}/approval",
        json={
            "spec_id": row["spec_id"],
            "proposer_signature": "proposer-sig-abc",
            "regulator_signature": "regulator-sig-xyz",
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["state"] == "DEPLOYED"


def test_single_signature_rejected(client, session_factory, gov_db):
    """POST approval with only one signature returns 400."""
    session_id = session_factory("AWAITING_APPROVAL")

    conn = sqlite3.connect(str(gov_db))
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        "SELECT spec_id FROM contract_spec WHERE session_id = ? AND status = 'validated'",
        (session_id,),
    ).fetchone()
    conn.close()

    resp = client.post(
        f"/api/governance/sessions/{session_id}/approval",
        json={
            "spec_id": row["spec_id"],
            "proposer_signature": "proposer-sig",
            "regulator_signature": "",  # missing
        },
    )
    assert resp.status_code == 400


def test_deployment_status(client, session_factory):
    """GET deployment returns deployment info."""
    session_id = session_factory("AWAITING_APPROVAL")

    resp = client.get(f"/api/governance/sessions/{session_id}/deployment")
    assert resp.status_code == 200
    data = resp.json()
    assert data["state"] == "AWAITING_APPROVAL"
    assert data["deployed"] is False
