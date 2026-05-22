"""Anchor publisher: commits one Merkle root per τ_anchor interval over
un-anchored event_log rows. Spec exec §7 (hybrid security)."""
from __future__ import annotations

import json
import logging
import sqlite3
import uuid
from pathlib import Path

from oasis.crypto import merkle


log = logging.getLogger(__name__)


def publish_anchor(
    *,
    db_path: str | Path,
    batch_max_size: int = 1000,
    mission_id: str | None = None,
) -> dict | None:
    """Anchor the next batch of un-anchored events. Returns the anchor
    row as a dict, or None if there were no pending events."""
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            "SELECT event_id, payload, sequence_number FROM event_log "
            "WHERE anchor_id IS NULL "
            "ORDER BY sequence_number ASC LIMIT ?",
            (batch_max_size,),
        ).fetchall()
        if not rows:
            return None

        # Canonical payload: JSON-stringify each event's payload, normalised
        # by sort_keys. Empty payload → '{}'.
        leaves: list[bytes] = []
        for r in rows:
            p = r["payload"] or "{}"
            try:
                obj = json.loads(p)
            except (TypeError, ValueError):
                obj = {}
            canonical = json.dumps(obj, sort_keys=True)
            leaves.append(canonical.encode())

        root = merkle.build_root(leaves)
        anchor_id = f"anchor-{uuid.uuid4().hex[:16]}"
        batch_start = rows[0]["sequence_number"]
        batch_end = rows[-1]["sequence_number"]

        conn.execute(
            "INSERT INTO on_chain_anchor "
            "(anchor_id, merkle_root_hex, batch_start_seq, batch_end_seq, "
            "event_count, mission_id) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (anchor_id, root.hex(), batch_start, batch_end, len(rows), mission_id),
        )
        event_ids = [r["event_id"] for r in rows]
        placeholders = ",".join("?" for _ in event_ids)
        conn.execute(
            f"UPDATE event_log SET anchor_id = ? "
            f"WHERE event_id IN ({placeholders})",
            (anchor_id, *event_ids),
        )
        conn.commit()
        log.info("anchored %d events as %s (root=%s)",
                  len(rows), anchor_id, root.hex()[:16])
        return {
            "anchor_id": anchor_id,
            "merkle_root_hex": root.hex(),
            "batch_start_seq": batch_start,
            "batch_end_seq": batch_end,
            "event_count": len(rows),
            "mission_id": mission_id,
        }
    finally:
        conn.close()
