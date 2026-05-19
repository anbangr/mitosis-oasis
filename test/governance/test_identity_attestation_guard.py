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
"""Bundle-0 bug-fix tests: IDENTITY_ATTESTATION string canonicalisation (T1–T3 + edge cases).

Test IDs map to the spec table in the plan:
  T1  — source must not contain 'IdentityVerificationResponse'; must contain
          'IDENTITY_ATTESTATION' at least twice.
  T2  — _guard_identity_to_proposal accepts a session where all 10 producers
          have sent IDENTITY_ATTESTATION messages.
  T3  — _guard_identity_to_proposal rejects a session with zero attestation rows
          (sanity baseline).
  T4  — existing governance suite is not broken; verified by running the full
          test/governance/ suite (covered by CI, not a new test here).

Edge cases:
  EC1 — extra BID_SUBMITTED rows in message_log must not inflate the attestation
          count and must not allow a session that would otherwise be quorum-blocked.
  EC2 — duplicate IDENTITY_ATTESTATION rows from the same sender_did must not
          be double-counted (guard uses COUNT DISTINCT).
"""

from __future__ import annotations

import inspect
import sqlite3
from pathlib import Path


import oasis.governance.state_machine as sm_module
from oasis.governance.schema import (
    create_governance_tables,
    seed_clerks,
    seed_constitution,
)
from oasis.governance.state_machine import _guard_identity_to_proposal


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _init_db(db_path: Path) -> None:
    create_governance_tables(db_path)
    seed_constitution(db_path)
    seed_clerks(db_path)


def _connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA foreign_keys = ON")
    conn.row_factory = sqlite3.Row
    return conn


def _create_session(conn: sqlite3.Connection, session_id: str) -> None:
    conn.execute(
        "INSERT INTO legislative_session (session_id, state, epoch) "
        "VALUES (?, 'IDENTITY_VERIFICATION', 1)",
        (session_id,),
    )
    conn.commit()


def _register_producers(conn: sqlite3.Connection, n: int) -> list[str]:
    """Insert n active producer agents with reputation_score=0.5; return DIDs."""
    dids = []
    for i in range(1, n + 1):
        did = f"did:mock:test-producer-{i}"
        conn.execute(
            "INSERT OR IGNORE INTO agent_registry "
            "(agent_did, agent_type, display_name, reputation_score, active) "
            "VALUES (?, 'producer', ?, 0.5, 1)",
            (did, f"Test Producer {i}"),
        )
        dids.append(did)
    conn.commit()
    return dids


def _insert_messages(
    conn: sqlite3.Connection,
    session_id: str,
    dids: list[str],
    msg_type: str,
) -> None:
    for did in dids:
        conn.execute(
            "INSERT INTO message_log (session_id, msg_type, sender_did) "
            "VALUES (?, ?, ?)",
            (session_id, msg_type, did),
        )
    conn.commit()


# ---------------------------------------------------------------------------
# T1 — canonical string checks (source inspection)
# ---------------------------------------------------------------------------


class TestAttestationStringCanonical:
    r"""T1: state_machine.py source must use 'IDENTITY_ATTESTATION', not the
    drifted 'IdentityVerificationResponse'."""

    def test_drifted_string_absent_from_source(self):
        """T1a: 'IdentityVerificationResponse' must not appear in state_machine source."""
        source = inspect.getsource(sm_module)
        assert "IdentityVerificationResponse" not in source, (
            "Drifted string 'IdentityVerificationResponse' still present in "
            "oasis/governance/state_machine.py — apply the bundle-0 fix."
        )

    def test_canonical_string_present_at_least_twice(self):
        """T1b: 'IDENTITY_ATTESTATION' must appear at least twice in state_machine source."""
        source = inspect.getsource(sm_module)
        count = source.count("'IDENTITY_ATTESTATION'")
        assert count >= 2, (
            f"Expected 'IDENTITY_ATTESTATION' to appear ≥2 times in "
            f"state_machine.py, found {count}. Apply the bundle-0 fix."
        )


# ---------------------------------------------------------------------------
# T2, T3, EC1, EC2 — guard behaviour with IDENTITY_ATTESTATION rows
# ---------------------------------------------------------------------------


class TestGuardIdentityAttestation:
    """Tests for _guard_identity_to_proposal with the canonical IDENTITY_ATTESTATION string."""

    def test_all_producers_attested_guard_allows(self, db_path: Path):
        """T2: guard accepts when all 10 producers have IDENTITY_ATTESTATION rows."""
        _init_db(db_path)
        session_id = "sess-t2-full"
        conn = _connect(db_path)
        _create_session(conn, session_id)
        dids = _register_producers(conn, 10)
        _insert_messages(conn, session_id, dids, "IDENTITY_ATTESTATION")

        result = _guard_identity_to_proposal(session_id, conn)
        conn.close()

        assert result.allowed is True, (
            f"Guard should allow with 10/10 IDENTITY_ATTESTATION rows. "
            f"Reason: {result.reason}"
        )

    def test_no_attestations_guard_rejects(self, db_path: Path):
        """T3 (sanity baseline): guard rejects when no attestation rows exist at all."""
        _init_db(db_path)
        session_id = "sess-t3-zero"
        conn = _connect(db_path)
        _create_session(conn, session_id)
        _register_producers(conn, 10)
        # No message_log rows inserted

        result = _guard_identity_to_proposal(session_id, conn)
        conn.close()

        assert result.allowed is False
        assert "Quorum not met" in result.reason

    def test_bid_submitted_rows_do_not_inflate_attestation_count(self, db_path: Path):
        """EC1: extra BID_SUBMITTED rows must not be counted as IDENTITY_ATTESTATION.

        Setup: 4 producers send IDENTITY_ATTESTATION (< 51% quorum for 10 total).
               6 remaining producers send BID_SUBMITTED.
        Expected after fix: guard rejects (only 4 IDENTITY_ATTESTATION rows counted).
        Before fix: guard finds 0 IdentityVerificationResponse → rejects → test FAILS (RED).
        """
        _init_db(db_path)
        session_id = "sess-ec1-mixed"
        conn = _connect(db_path)
        _create_session(conn, session_id)
        dids = _register_producers(conn, 10)

        # 4 real attestations — below the 51% quorum
        _insert_messages(conn, session_id, dids[:4], "IDENTITY_ATTESTATION")
        # 6 noise rows that must not be counted; counting them would incorrectly pass.
        _insert_messages(conn, session_id, dids[4:], "BID_SUBMITTED")

        result = _guard_identity_to_proposal(session_id, conn)
        conn.close()

        assert result.allowed is False
        assert "Quorum not met" in result.reason

    def test_duplicate_attestations_not_double_counted(self, db_path: Path):
        """EC2: COUNT DISTINCT — duplicate rows from same sender must not reach quorum.

        Setup: 4 distinct producers attested (4/10 = 40% < 51% quorum), but
               producer-1 sent 7 duplicate IDENTITY_ATTESTATION messages.
        Naive COUNT would yield 10, reaching quorum — COUNT DISTINCT must not.
        """
        _init_db(db_path)
        session_id = "sess-ec2-dup"
        conn = _connect(db_path)
        _create_session(conn, session_id)
        dids = _register_producers(conn, 10)

        # 7 duplicates from dids[0]
        _insert_messages(conn, session_id, [dids[0]] * 7, "IDENTITY_ATTESTATION")
        # 3 more distinct producers (total distinct = 4)
        _insert_messages(conn, session_id, dids[1:4], "IDENTITY_ATTESTATION")

        result = _guard_identity_to_proposal(session_id, conn)
        conn.close()

        assert result.allowed is False, (
            "Guard should reject: only 4 distinct senders / 10 producers = 40% < 51% quorum. "
            "Duplicate rows from the same sender must not be double-counted."
        )
        assert "Quorum not met" in result.reason

    def test_partial_attestation_below_quorum_rejects(self, db_path: Path):
        """Guard rejects when IDENTITY_ATTESTATION count is below the 51% quorum threshold."""
        _init_db(db_path)
        session_id = "sess-partial"
        conn = _connect(db_path)
        _create_session(conn, session_id)
        dids = _register_producers(conn, 10)
        # Only 4 of 10 attest (40% < 51%)
        _insert_messages(conn, session_id, dids[:4], "IDENTITY_ATTESTATION")

        result = _guard_identity_to_proposal(session_id, conn)
        conn.close()

        assert result.allowed is False
        assert "Quorum not met" in result.reason
