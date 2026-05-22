"""Impeachment module — supermajority motion, tally, and full stake slash.

Spec §2.1-2.2: ceil(2q/3) adjudicators must sign an impeachment motion.
On acceptance: 100% of stake → treasury, target banned in both registries.
"""

from __future__ import annotations

import json
import math
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Union

from oasis.adjudication.coi import _resolve_adjudicator_did_from_signer
from oasis.crypto.eip712 import verify
from oasis.crypto.typed_data import DOMAIN


@dataclass
class ImpeachmentVerdict:
    """Result of tallying an impeachment motion."""

    status: str
    slashed_amount: float | None = None
    reason: str = ""
    executed_at: str | None = None


def _required_threshold(q: int) -> int:
    """Return the minimum number of valid signatures required for impeachment.

    Formula: ceil(2q/3) where q is the adjudicator quorum.
    """
    return math.ceil(2 * q / 3)


def _get_quorum_q(gov_db_path: Union[str, Path]) -> int:
    """Read ``adjudicator_quorum`` from the constitution table.

    Falls back to ``7`` when the parameter is absent (pre-migration DB).
    """
    conn = sqlite3.connect(str(gov_db_path))
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute(
            "SELECT param_value FROM constitution WHERE param_name = ?",
            ("adjudicator_quorum",),
        ).fetchone()
        return int(row["param_value"]) if row else 7
    finally:
        conn.close()


def submit_motion(
    *,
    motion_id: str,
    target_did: str,
    evidence_cid: str,
    signatures: list[dict],
    adj_db_path: Union[str, Path],
    gov_db_path: Union[str, Path],
    agents_in_mission: tuple = (),
) -> None:
    """Persist a pending impeachment motion.

    Parameters
    ----------
    motion_id:
        Unique identifier for the motion.
    target_did:
        DID of the adjudicator being impeached.
    evidence_cid:
        IPFS CID linking to the evidence bundle.
    signatures:
        List of ``{"signer": "0x...", "signature": "0x..."}`` dicts.
    adj_db_path:
        Path to the adjudication SQLite database.
    gov_db_path:
        Path to the governance SQLite database.
    agents_in_mission:
        Agent DIDs in the target mission (for future COI checks).
    """
    threshold = _required_threshold(_get_quorum_q(gov_db_path))
    conn = sqlite3.connect(str(adj_db_path))
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        conn.execute(
            "INSERT INTO impeachment "
            "(motion_id, target_did, evidence_cid, signatures_json, "
            "signatures_count, required_threshold, status) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                motion_id,
                target_did,
                evidence_cid,
                json.dumps(signatures),
                len(signatures),
                threshold,
                "pending",
            ),
        )
        conn.commit()
    finally:
        conn.close()


def tally_motion(
    *,
    motion_id: str,
    adj_db_path: Union[str, Path],
    gov_db_path: Union[str, Path] | None = None,
    agents_in_mission: tuple = (),
) -> ImpeachmentVerdict:
    """Tally signatures for an impeachment motion and apply consequences.

    Returns an :class:`ImpeachmentVerdict` describing the outcome.
    """
    conn = sqlite3.connect(str(adj_db_path))
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute(
            "SELECT * FROM impeachment WHERE motion_id = ?",
            (motion_id,),
        ).fetchone()

        if row is None:
            return ImpeachmentVerdict(
                status="rejected",
                reason="motion not found",
            )

        if row["status"] != "pending":
            return ImpeachmentVerdict(
                status=row["status"],
                slashed_amount=row["slashed_amount"],
                executed_at=row["executed_at"],
            )

        target_did = row["target_did"]
        evidence_cid = row["evidence_cid"]
        threshold = row["required_threshold"]
        signatures = json.loads(row["signatures_json"])

        message = {
            "target_did": target_did,
            "evidence_cid": evidence_cid,
            "motion_id": motion_id,
        }

        valid_signers: set[str] = set()
        for sig_entry in signatures:
            signer_addr = sig_entry.get("signer", "")
            sig_hex = sig_entry.get("signature", "")

            if sig_hex.startswith("0x") or sig_hex.startswith("0X"):
                sig_hex = sig_hex[2:]

            try:
                sig_bytes = bytes.fromhex(sig_hex)
            except ValueError:
                continue

            if not verify(
                domain=DOMAIN,
                primary_type="Impeachment",
                message=message,
                signature=sig_bytes,
                expected_signer=signer_addr,
            ):
                continue

            # Membership gate: signer must be a registered, non-banned adjudicator
            resolved_did = _resolve_adjudicator_did_from_signer(
                signer_address=signer_addr,
                adj_db_path=str(adj_db_path),
                gov_db_path=str(gov_db_path) if gov_db_path else None,
            )
            if resolved_did is None:
                continue

            valid_signers.add(signer_addr.lower())

        valid_count = len(valid_signers)

        if valid_count >= threshold:
            status = "accepted"
            slashed_amount = _apply_impeachment_consequences(
                conn=conn,
                target_did=target_did,
                adj_db_path=adj_db_path,
                gov_db_path=gov_db_path,
            )
            reason = ""
        else:
            status = "rejected"
            slashed_amount = None
            reason = f"below threshold ({valid_count} of {threshold})"

        conn.execute(
            "UPDATE impeachment SET status = ?, slashed_amount = ?, "
            "executed_at = CURRENT_TIMESTAMP WHERE motion_id = ?",
            (status, slashed_amount, motion_id),
        )
        conn.commit()

        return ImpeachmentVerdict(
            status=status,
            slashed_amount=slashed_amount,
            reason=reason,
            executed_at=conn.execute("SELECT CURRENT_TIMESTAMP").fetchone()[0]
            if status == "accepted"
            else None,
        )
    finally:
        conn.close()


def _apply_impeachment_consequences(
    *,
    conn: sqlite3.Connection,
    target_did: str,
    adj_db_path: Union[str, Path],
    gov_db_path: Union[str, Path] | None,
) -> float:
    """Apply the full stake slash and ban for an accepted impeachment.

    Returns the slashed amount.
    """
    # Get current locked stake
    bal_row = conn.execute(
        "SELECT locked_stake FROM agent_balance WHERE agent_did = ?",
        (target_did,),
    ).fetchone()
    locked = bal_row["locked_stake"] if bal_row else 0.0

    # Zero the target's balances
    conn.execute(
        "UPDATE agent_balance SET locked_stake = 0, total_balance = 0 "
        "WHERE agent_did = ?",
        (target_did,),
    )

    # Compute new treasury balance
    treasury_row = conn.execute(
        "SELECT balance_after FROM treasury ORDER BY entry_id DESC LIMIT 1"
    ).fetchone()
    old_treasury = treasury_row["balance_after"] if treasury_row else 0.0
    new_treasury = old_treasury + locked

    # Insert treasury row for impeachment slash
    conn.execute(
        "INSERT INTO treasury (agent_did, entry_type, amount, balance_after) "
        "VALUES (?, 'impeachment_slash', ?, ?)",
        (target_did, locked, new_treasury),
    )

    # Ban in adjudicator_registry
    conn.execute(
        "UPDATE adjudicator_registry SET is_banned = 1 WHERE adjudicator_did = ?",
        (target_did,),
    )

    # Ban in agent_registry (governance DB)
    if gov_db_path is not None:
        conn_gov = sqlite3.connect(str(gov_db_path))
        conn_gov.execute("PRAGMA foreign_keys = ON")
        try:
            conn_gov.execute(
                "UPDATE agent_registry SET banned = 1, active = 0 WHERE agent_did = ?",
                (target_did,),
            )
            conn_gov.commit()
        finally:
            conn_gov.close()

    return locked
