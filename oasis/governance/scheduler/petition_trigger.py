# Licensed to the Apache Software Foundation (ASF) under one
# or more contributor license agreements.  See the NOTICE file
# distributed with this work for additional information
# regarding copyright ownership.  The ASF licenses this file
# to you under the Apache License, Version 2.0 (the
# "License"); you may not use this file except in compliance
# with the License.  You may obtain a copy of the License at
#
#   http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing,
# software distributed under the License is distributed on an
# "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY
# KIND, either express or implied.  See the License for the
# specific language governing permissions and limitations
# under the License.
"""Petition-based legislative-session trigger (spec leg §2.2).

Agents accumulate signatures; once ≥``petition_threshold`` (default 0.20)
of active producers sign, a session is fired with ``trigger='petition'``.
"""

from __future__ import annotations

import sqlite3
import uuid
from pathlib import Path


def accumulate_signature(
    *,
    petition_id: str,
    signer_did: str,
    signature_hex: str,
    db_path: str | Path,
) -> None:
    """Insert a (petition_id, signer_did, signature) row.

    The ``UNIQUE (petition_id, signer_did)`` constraint on
    ``petition_signature`` enforces no duplicates — a second call from
    the same signer for the same petition raises ``sqlite3.IntegrityError``.
    """
    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute(
            "INSERT INTO petition_signature "
            "(petition_id, signer_did, signature_hex) "
            "VALUES (?, ?, ?)",
            (petition_id, signer_did, signature_hex),
        )
        conn.commit()
    finally:
        conn.close()


def check_threshold(
    *,
    petition_id: str,
    db_path: str | Path,
    threshold: float = 0.20,
) -> bool:
    """True iff distinct-signature count / active-producer count ≥ threshold.

    Returns ``False`` when there are zero active producers (no divide-by-zero).
    """
    conn = sqlite3.connect(str(db_path))
    try:
        sig_count = conn.execute(
            "SELECT COUNT(DISTINCT signer_did) FROM petition_signature "
            "WHERE petition_id = ?",
            (petition_id,),
        ).fetchone()[0]
        active = conn.execute(
            "SELECT COUNT(*) FROM agent_registry "
            "WHERE agent_type = 'producer' AND active = 1"
        ).fetchone()[0]
        if active == 0:
            return False
        return (sig_count / active) >= threshold
    finally:
        conn.close()


def fire_petition(
    *,
    petition_id: str,
    db_path: str | Path,
) -> str:
    """Create a legislative_session triggered by petition; mark petition.fired_at.

    Raises ``ValueError`` if the petition does not exist.
    """
    conn = sqlite3.connect(str(db_path))
    try:
        pet = conn.execute(
            "SELECT title, proposed_mission FROM petition WHERE petition_id = ?",
            (petition_id,),
        ).fetchone()
        if pet is None:
            raise ValueError(f"petition {petition_id} not found")
        session_id = f"petition-{uuid.uuid4().hex[:12]}"
        conn.execute(
            "INSERT INTO legislative_session "
            "(session_id, state, trigger) "
            "VALUES (?, 'SESSION_INIT', 'petition')",
            (session_id,),
        )
        conn.execute(
            "UPDATE petition SET fired_at = CURRENT_TIMESTAMP, "
            "fired_session_id = ? WHERE petition_id = ?",
            (session_id, petition_id),
        )
        conn.commit()
        return session_id
    finally:
        conn.close()
