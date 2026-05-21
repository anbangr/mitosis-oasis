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
"""Rotation policy helpers for adjudication.

Prevents any single adjudicator from monopolising decisions of a given
type by enforcing a ``max_consecutive`` limit.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Union


@dataclass
class RotationResult:
    """Outcome of an ``enforce_rotation`` check."""

    allowed: bool
    reason: str


def last_n_decisions(
    *,
    adjudicator_did: str,
    n: int,
    db_path: Union[str, Path],
    decision_type: str | None = None,
) -> list[sqlite3.Row]:
    """Return the most recent *n* decisions issued by *adjudicator_did*.

    Parameters
    ----------
    adjudicator_did:
        The DID of the adjudicator whose decisions are queried.
    n:
        Maximum number of rows to return.
    db_path:
        Path to the SQLite database containing ``adjudication_decision``.
    decision_type:
        If given, restrict to decisions of this type (e.g. ``'freeze'``).

    Returns
    -------
    list[sqlite3.Row]
        Rows ordered by ``created_at DESC``.
    """
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        if decision_type is not None:
            rows = conn.execute(
                "SELECT * FROM adjudication_decision "
                "WHERE issued_by_did = ? AND decision_type = ? "
                "ORDER BY created_at DESC LIMIT ?",
                (adjudicator_did, decision_type, n),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM adjudication_decision "
                "WHERE issued_by_did = ? "
                "ORDER BY created_at DESC LIMIT ?",
                (adjudicator_did, n),
            ).fetchall()
        return list(rows)
    finally:
        conn.close()


def enforce_rotation(
    *,
    adjudicator_did: str,
    decision_type: str,
    max_consecutive: int,
    db_path: Union[str, Path],
) -> RotationResult:
    """Block a decision when the adjudicator has already hit the limit.

        A decision is blocked only when ``max_consecutive`` or more prior
    decisions of the same *decision_type* were all issued by
        *adjudicator_did*.  An intervening decision by a different
        adjudicator resets the streak.

        Parameters
        ----------
        adjudicator_did:
            DID of the adjudator about to issue a decision.
        decision_type:
            Type of decision being considered (e.g. ``'freeze'``).
        max_consecutive:
            Maximum number of consecutive decisions of this type allowed
            from a single adjudicator.
        db_path:
            Path to the SQLite database containing ``adjudication_decision``.

        Returns
        -------
        RotationResult
            ``allowed=False`` when the streak has been exceeded;
            ``allowed=True`` otherwise.
    """
    if max_consecutive <= 0:
        return RotationResult(allowed=True, reason="")

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            "SELECT issued_by_did FROM adjudication_decision "
            "WHERE decision_type = ? "
            "ORDER BY created_at DESC LIMIT ?",
            (decision_type, max_consecutive),
        ).fetchall()

        if len(rows) >= max_consecutive and all(
            row["issued_by_did"] == adjudicator_did for row in rows
        ):
            return RotationResult(
                allowed=False,
                reason=(
                    f"Rotation policy violated: adjudicator {adjudicator_did} "
                    f"has issued {len(rows)} consecutive {decision_type} decisions"
                ),
            )

        return RotationResult(allowed=True, reason="")
    finally:
        conn.close()
