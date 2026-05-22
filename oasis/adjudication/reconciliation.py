"""Mission-boundary reconciliation (spec exec §7.9).

At Mission completion, compare event_log entries vs the persisted
on_chain_anchor rows. Recompute each anchor's Merkle root from the
current event_log payloads and compare against the stored root.

Failure modes:
    1. Events with this mission_id that have no anchor_id → DIVERGED.
    2. Recomputed Merkle root for an anchor's events ≠ stored root → DIVERGED.
    3. Anchor row exists but referenced events are missing → DIVERGED.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from oasis.crypto import merkle


@dataclass
class ReconciliationResult:
    status: str  # "PASS" | "DIVERGED"
    mission_id: str
    divergence_count: int
    reason: str = ""


def reconcile_mission(
    *,
    mission_id: str,
    db_path: str | Path,
) -> ReconciliationResult:
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        # 1. Any unanchored events for this mission?
        unanchored = conn.execute(
            "SELECT COUNT(*) FROM event_log WHERE mission_id = ? AND anchor_id IS NULL",
            (mission_id,),
        ).fetchone()[0]
        if unanchored:
            return ReconciliationResult(
                status="DIVERGED",
                mission_id=mission_id,
                divergence_count=unanchored,
                reason=f"{unanchored} unanchored events for mission {mission_id}",
            )

        # 2. For each anchor row referencing this mission, recompute Merkle.
        anchors = conn.execute(
            "SELECT anchor_id, merkle_root_hex, batch_start_seq, "
            "batch_end_seq FROM on_chain_anchor "
            "WHERE mission_id = ?",
            (mission_id,),
        ).fetchall()
        total_divergence = 0
        last_reason = ""
        for anchor in anchors:
            events = conn.execute(
                "SELECT payload FROM event_log "
                "WHERE anchor_id = ? "
                "ORDER BY sequence_number ASC",
                (anchor["anchor_id"],),
            ).fetchall()
            leaves = []
            for e in events:
                p = e["payload"] or "{}"
                try:
                    obj = json.loads(p)
                except (TypeError, ValueError):
                    obj = {}
                leaves.append(json.dumps(obj, sort_keys=True).encode())
            computed = merkle.build_root(leaves).hex()
            if computed != anchor["merkle_root_hex"]:
                total_divergence += 1
                last_reason = (
                    f"anchor {anchor['anchor_id']}: "
                    f"merkle mismatch (computed {computed[:16]}... vs "
                    f"stored {anchor['merkle_root_hex'][:16]}...)"
                )

        if total_divergence:
            return ReconciliationResult(
                status="DIVERGED",
                mission_id=mission_id,
                divergence_count=total_divergence,
                reason=last_reason,
            )

        return ReconciliationResult(
            status="PASS",
            mission_id=mission_id,
            divergence_count=0,
        )
    finally:
        conn.close()
