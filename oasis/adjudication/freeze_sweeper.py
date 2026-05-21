# =========== Copyright 2023 @ CAMEL-AI.org. All Rights Reserved. ===========
# Licensed under the Apache License, Version 2.0 (the “License”);
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an “AS IS” BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
# =========== Copyright 2023 @ CAMEL-AI.org. All Rights Reserved. ===========
"""Freeze sweeper — auto-lift freezes older than max_duration_ms."""

from __future__ import annotations

import sqlite3
import uuid
from pathlib import Path
from typing import Union


def sweep_expired_freezes(
    *,
    db_path: Union[str, Path],
    max_duration_ms: int = 259_200_000,
) -> int:
    """Lift freezes older than ``max_duration_ms`` that have no extension
    and no subsequent unfreeze decision.

    For each matching freeze row, an ``unfreeze`` decision is inserted with
    ``reason`` containing *auto-lifted* and ``layer1_result='sweeper'``.

    Returns the count of unfreeze decisions inserted in this call.
    """
    max_duration_seconds = max_duration_ms // 1000

    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        cursor = conn.execute(
            f"""
            SELECT d.decision_id, d.agent_did, d.frozen_at
            FROM adjudication_decision d
            WHERE d.decision_type = 'freeze'
              AND d.manual_extension = 0
              AND d.frozen_at <= datetime('now', '-{max_duration_seconds} seconds')
              AND NOT EXISTS (
                  SELECT 1 FROM adjudication_decision u
                  WHERE u.agent_did = d.agent_did
                    AND u.decision_type = 'unfreeze'
                    AND u.created_at > d.frozen_at
              )
            """
        )
        expired = cursor.fetchall()

        inserted = 0
        for _decision_id, agent_did, _frozen_at in expired:
            unfreeze_id = uuid.uuid4().hex[:12]
            conn.execute(
                """
                INSERT INTO adjudication_decision
                (decision_id, agent_did, decision_type, severity, reason,
                 layer1_result, created_at)
                VALUES (?, ?, 'unfreeze', 'INFO', 'auto-lifted after 72h (spec §2.4)',
                        'sweeper', strftime('%Y-%m-%d %H:%M:%f', 'now'))
                """,
                (unfreeze_id, agent_did),
            )
            inserted += 1

        conn.commit()
        return inserted
    finally:
        conn.close()
