"""P8.8 — Codification API tests."""
from __future__ import annotations

import sqlite3


def test_submit_spec(client, session_factory, gov_db):
    """POST codification/spec compiles and validates a spec."""
    session_id = session_factory("CODIFICATION")

    # Get the proposal ID
    conn = sqlite3.connect(str(gov_db))
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        "SELECT proposal_id FROM proposal WHERE session_id = ?",
        (session_id,),
    ).fetchone()
    conn.close()
    assert row is not None

    resp = client.post(
        f"/api/governance/sessions/{session_id}/codification/spec",
        json={"proposal_id": row["proposal_id"]},
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["status"] == "validated"


def test_get_spec(client, session_factory):
    """GET codification/spec returns specs for a session."""
    session_id = session_factory("CODIFICATION")

    resp = client.get(f"/api/governance/sessions/{session_id}/codification/spec")
    assert resp.status_code == 200
    data = resp.json()
    assert "specs" in data


def test_constitutional_validation_failure(client, session_factory, gov_db):
    """POST codification/spec returns 400 on constitutional violation."""
    session_id = session_factory("CODIFICATION")

    # Tamper with the constitution to make budget cap very low
    conn = sqlite3.connect(str(gov_db))
    conn.execute(
        "UPDATE constitution SET param_value = 1.0 WHERE param_name = 'budget_cap_max'"
    )
    conn.commit()
    conn.close()

    # Get proposal
    conn = sqlite3.connect(str(gov_db))
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        "SELECT proposal_id FROM proposal WHERE session_id = ?",
        (session_id,),
    ).fetchone()
    conn.close()

    resp = client.post(
        f"/api/governance/sessions/{session_id}/codification/spec",
        json={"proposal_id": row["proposal_id"]},
    )
    assert resp.status_code == 400
