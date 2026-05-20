# =========== Copyright 2023 @ CAMEL-AI.org. All Rights Reserved. ===========
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
# =========== Copyright 2023 @ CAMEL-AI.org. All Rights Reserved. ===========
r"""T1–T6 + edge cases: Schema migration (public_key, signature, payload_json)
and canonical_signed_bytes helper.

Coverage target: ≥80%.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from oasis.governance.messages import (
    DAGProposal,
    IdentityAttestation,
    IdentityVerificationRequest,
    LegislativeApproval,
    MessageType,
    RegulatoryDecision,
    TaskBid,
)
from oasis.governance.schema import create_governance_tables, seed_constitution


# ---------------------------------------------------------------------------
# Schema helpers
# ---------------------------------------------------------------------------


def _table_columns(db_path: Path, table_name: str) -> dict[str, dict]:
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(f"PRAGMA table_info({table_name})").fetchall()
        return {r["name"]: dict(r) for r in rows}
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# T1 — public_key column exists in agent_registry
# ---------------------------------------------------------------------------


def test_t1_public_key_column_exists(tmp_path: Path):
    r"""T1: agent_registry has nullable TEXT public_key after create_governance_tables."""
    db_path = tmp_path / "g.db"
    create_governance_tables(str(db_path))
    cols = _table_columns(db_path, "agent_registry")
    assert "public_key" in cols, "agent_registry missing public_key column"
    assert cols["public_key"]["type"] == "TEXT", "public_key must be TEXT"
    assert cols["public_key"]["notnull"] == 0, "public_key must be nullable"


# ---------------------------------------------------------------------------
# T2 — signature column exists in message_log
# ---------------------------------------------------------------------------


def test_t2_signature_column_exists(tmp_path: Path):
    r"""T2: message_log has nullable TEXT signature after create_governance_tables."""
    db_path = tmp_path / "g.db"
    create_governance_tables(str(db_path))
    cols = _table_columns(db_path, "message_log")
    assert "signature" in cols, "message_log missing signature column"
    assert cols["signature"]["type"] == "TEXT", "signature must be TEXT"
    assert cols["signature"]["notnull"] == 0, "signature must be nullable"


# ---------------------------------------------------------------------------
# T3 — payload_json column exists in message_log
# ---------------------------------------------------------------------------


def test_t3_payload_json_column_exists(tmp_path: Path):
    r"""T3: message_log has nullable TEXT payload_json after create_governance_tables."""
    db_path = tmp_path / "g.db"
    create_governance_tables(str(db_path))
    cols = _table_columns(db_path, "message_log")
    assert "payload_json" in cols, "message_log missing payload_json column"
    assert cols["payload_json"]["type"] == "TEXT", "payload_json must be TEXT"
    assert cols["payload_json"]["notnull"] == 0, "payload_json must be nullable"


# ---------------------------------------------------------------------------
# T4 — Idempotent migration
# ---------------------------------------------------------------------------


def test_t4_migration_idempotent(tmp_path: Path):
    r"""T4: Running create_governance_tables twice adds columns once, no error."""
    db_path = tmp_path / "g.db"
    create_governance_tables(str(db_path))
    # Second call must not raise
    create_governance_tables(str(db_path))

    # Columns still present exactly once
    cols = _table_columns(db_path, "agent_registry")
    assert list(cols.keys()).count("public_key") == 1
    cols = _table_columns(db_path, "message_log")
    assert list(cols.keys()).count("signature") == 1
    assert list(cols.keys()).count("payload_json") == 1


# ---------------------------------------------------------------------------
# T5 — canonical_signed_bytes deterministic per MSG type
# ---------------------------------------------------------------------------


def test_t5_canonical_signed_bytes_deterministic():
    r"""T5: canonical_signed_bytes is deterministic and covers the signed field set."""
    from oasis.governance.messages import canonical_signed_bytes

    msg1 = IdentityAttestation(
        session_id="s",
        agent_did="did:key:zX",
        signature="ab" * 64,
        reputation_score=0.5,
        agent_type="producer",
    )
    msg2 = IdentityAttestation(
        session_id="s",
        agent_did="did:key:zX",
        signature="ab" * 64,
        reputation_score=0.5,
        agent_type="producer",
    )
    assert canonical_signed_bytes(msg1) == canonical_signed_bytes(msg2)

    # Decode and verify JSON structure
    data = json.loads(canonical_signed_bytes(msg1).decode("utf-8"))
    assert data["msg_type"] == MessageType.IDENTITY_ATTESTATION.value
    assert data["session_id"] == "s"
    assert "agent_did" in data
    assert "reputation_score" in data
    assert "agent_type" in data
    assert "timestamp" not in data, "timestamp must be excluded from canonical bytes"
    assert "signature" not in data, "signature must be excluded from canonical bytes"

    # Verify compact separators (no spaces)
    raw = canonical_signed_bytes(msg1).decode("utf-8")
    assert ", " not in raw, "must use separators=(',', ':') — no space after comma"
    assert ": " not in raw, "must use separators=(',', ':') — no space after colon"

    # Verify sort_keys applied
    key_order = list(data.keys())
    assert key_order == sorted(key_order), "top-level keys must be sorted"


# ---------------------------------------------------------------------------
# T6 — canonical bytes excludes server-set fields (timestamp)
# ---------------------------------------------------------------------------


def test_t6_canonical_excludes_timestamp():
    r"""T6: Two messages with identical signed fields but different timestamps yield
    identical canonical bytes."""
    from oasis.governance.messages import canonical_signed_bytes

    a = IdentityAttestation(
        session_id="s",
        agent_did="did:key:zX",
        signature="ab" * 64,
        reputation_score=0.5,
        agent_type="producer",
    )
    import time

    time.sleep(0.01)
    b = IdentityAttestation(
        session_id="s",
        agent_did="did:key:zX",
        signature="ab" * 64,
        reputation_score=0.5,
        agent_type="producer",
    )
    assert a.timestamp != b.timestamp, "timestamps should differ"
    assert canonical_signed_bytes(a) == canonical_signed_bytes(b)


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


def test_seed_constitution_runs_after_alters(tmp_path: Path):
    r"""seed_constitution continues to work after the ALTER statements."""
    db_path = tmp_path / "g.db"
    create_governance_tables(str(db_path))
    seed_constitution(str(db_path))

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute(
            "SELECT param_value FROM constitution WHERE param_name = 'quorum_threshold'"
        ).fetchone()
        assert row is not None
        assert row["param_value"] == pytest.approx(0.60)
    finally:
        conn.close()


def test_nullable_columns_accept_null_rows(tmp_path: Path):
    r"""NULL signature and payload_json rows can be inserted and read back."""
    db_path = tmp_path / "g.db"
    create_governance_tables(str(db_path))
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        conn.execute(
            "INSERT INTO legislative_session (session_id, state) VALUES (?, ?)",
            ("sess", "SESSION_INIT"),
        )
        conn.execute(
            "INSERT INTO message_log "
            "(session_id, msg_type, sender_did, payload, signature, payload_json) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            ("sess", "IDENTITY_VERIFICATION_REQUEST", "system", "", None, None),
        )
        conn.commit()

        row = conn.execute(
            "SELECT signature, payload_json FROM message_log WHERE session_id = ?",
            ("sess",),
        ).fetchone()
        assert row[0] is None
        assert row[1] is None
    finally:
        conn.close()


def test_canonical_signed_bytes_raises_for_unknown_type():
    r"""canonical_signed_bytes raises TypeError for unrecognised msg_type values."""
    from oasis.governance.messages import canonical_signed_bytes

    fake_type = type("FakeType", (), {"value": "UNKNOWN_TYPE"})()
    fake_msg = type("FakeMsg", (), {"msg_type": fake_type})()
    with pytest.raises(TypeError):
        canonical_signed_bytes(fake_msg)


def test_float_formatting_uses_dot_six_f():
    r"""Floats in canonical bytes are formatted via format(v, '.6f')."""
    from oasis.governance.messages import canonical_signed_bytes

    msg = IdentityAttestation(
        session_id="s",
        agent_did="did:key:zX",
        signature="ab" * 64,
        reputation_score=0.123456789,
        agent_type="producer",
    )
    data = json.loads(canonical_signed_bytes(msg).decode("utf-8"))
    assert data["reputation_score"] == "0.123457", (
        "float must be formatted with format(v, '.6f')"
    )


def test_nested_dict_sort_keys_recursively():
    r"""Nested dict keys are sorted recursively; list order is preserved."""
    from oasis.governance.messages import canonical_signed_bytes

    msg = DAGProposal(
        session_id="s",
        proposer_did="did:key:zP",
        dag_spec={
            "z_key": 1,
            "a_key": {"nested_z": 2, "nested_a": 3},
            "nodes": [],
        },
        rationale="test",
        token_budget_total=100.0,
        deadline_ms=60000,
    )
    raw = canonical_signed_bytes(msg).decode("utf-8")
    # Outer keys sorted
    assert raw.index('"dag_spec"') < raw.index('"deadline_ms"')
    assert raw.index('"deadline_ms"') < raw.index('"msg_type"')
    assert raw.index('"msg_type"') < raw.index('"proposer_did"')
    # Nested dict keys sorted
    assert raw.index('"nested_a"') < raw.index('"nested_z"')


def test_list_order_preserved_in_canonical():
    r"""List element order is semantically meaningful and preserved."""
    from oasis.governance.messages import canonical_signed_bytes

    msg = RegulatoryDecision(
        session_id="s",
        approved_bids=["bid_z", "bid_a"],
        rejected_bids=["bid_b"],
        fairness_score=0.5,
        compliance_flags=["flag2", "flag1"],
        regulatory_signature="cd" * 64,
    )
    data = json.loads(canonical_signed_bytes(msg).decode("utf-8"))
    assert data["approved_bids"] == ["bid_z", "bid_a"]
    assert data["compliance_flags"] == ["flag2", "flag1"]


def test_canonical_signed_bytes_all_msg_types():
    r"""Every MSG type in the canonical table produces deterministic bytes
    with the correct field set."""
    from oasis.governance.messages import (
        CodedContractSpec,
        canonical_signed_bytes,
    )

    # MSG1 — IdentityVerificationRequest
    msg1 = IdentityVerificationRequest(session_id="s1", min_reputation=0.1)
    cb1 = canonical_signed_bytes(msg1)
    data1 = json.loads(cb1.decode("utf-8"))
    assert data1["msg_type"] == MessageType.IDENTITY_VERIFICATION_REQUEST.value
    assert "min_reputation" in data1

    # MSG2 — IdentityAttestation
    msg2 = IdentityAttestation(
        session_id="s2",
        agent_did="did:key:zA",
        signature="ef" * 64,
        reputation_score=0.75,
        agent_type="clerk",
    )
    cb2 = canonical_signed_bytes(msg2)
    data2 = json.loads(cb2.decode("utf-8"))
    assert data2["msg_type"] == MessageType.IDENTITY_ATTESTATION.value
    assert "agent_did" in data2
    assert "reputation_score" in data2
    assert "agent_type" in data2

    # MSG3 — DAGProposal
    msg3 = DAGProposal(
        session_id="s3",
        proposer_did="did:key:zP",
        dag_spec={"nodes": []},
        rationale="r",
        token_budget_total=50.0,
        deadline_ms=1000,
    )
    cb3 = canonical_signed_bytes(msg3)
    data3 = json.loads(cb3.decode("utf-8"))
    assert data3["msg_type"] == MessageType.DAG_PROPOSAL.value
    assert "proposer_did" in data3
    assert "dag_spec" in data3
    assert "rationale" in data3
    assert "token_budget_total" in data3
    assert "deadline_ms" in data3

    # MSG4 — TaskBid
    msg4 = TaskBid(
        session_id="s4",
        task_node_id="n1",
        bidder_did="did:key:zB",
        service_id="svc",
        proposed_code_hash="hash1234",
        stake_amount=10.0,
        estimated_latency_ms=5000,
        quoted_price=100.0,
        capability_match=0.8,
        pop_tier_acceptance=2,
    )
    cb4 = canonical_signed_bytes(msg4)
    data4 = json.loads(cb4.decode("utf-8"))
    assert data4["msg_type"] == MessageType.TASK_BID.value
    assert "task_node_id" in data4
    assert "bidder_did" in data4
    assert "service_id" in data4
    assert "proposed_code_hash" in data4
    assert "stake_amount" in data4
    assert "estimated_latency_ms" in data4
    assert "quoted_price" in data4
    assert "capability_match" in data4
    assert "pop_tier_acceptance" in data4

    # MSG5 — RegulatoryDecision
    msg5 = RegulatoryDecision(
        session_id="s5",
        approved_bids=["bid1", "bid2"],
        rejected_bids=["bid3"],
        fairness_score=0.9,
        compliance_flags=["flag1"],
        regulatory_signature="gh" * 64,
    )
    cb5 = canonical_signed_bytes(msg5)
    data5 = json.loads(cb5.decode("utf-8"))
    assert data5["msg_type"] == MessageType.REGULATORY_DECISION.value
    assert "approved_bids" in data5
    assert "rejected_bids" in data5
    assert "fairness_score" in data5
    assert "compliance_flags" in data5

    # MSG6 — CodedContractSpec
    msg6 = CodedContractSpec(
        session_id="s6",
        collaboration_contract_spec={"a": 1},
        guardian_module_spec={"b": 2},
        verification_module_spec={"c": 3},
        gate_module_spec={"d": 4},
        service_contract_specs={"e": 5},
        validation_proof="proof123",
    )
    cb6 = canonical_signed_bytes(msg6)
    data6 = json.loads(cb6.decode("utf-8"))
    assert data6["msg_type"] == MessageType.CODED_CONTRACT_SPEC.value
    assert "collaboration_contract_spec" in data6
    assert "guardian_module_spec" in data6
    assert "verification_module_spec" in data6
    assert "gate_module_spec" in data6
    assert "service_contract_specs" in data6
    assert "validation_proof" in data6

    # MSG7 — LegislativeApproval
    msg7 = LegislativeApproval(
        session_id="s7",
        spec_id="spec1",
        speaker_signature="ij" * 64,
        regulator_signature="kl" * 64,
    )
    cb7 = canonical_signed_bytes(msg7)
    data7 = json.loads(cb7.decode("utf-8"))
    assert data7["msg_type"] == MessageType.LEGISLATIVE_APPROVAL.value
    assert "spec_id" in data7
