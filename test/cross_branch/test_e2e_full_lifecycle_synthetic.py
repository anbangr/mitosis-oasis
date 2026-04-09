"""E2E: Full 3-branch pipeline — legislate → execute (synthetic) → settle → reputation."""
from __future__ import annotations

import sqlite3

from oasis.config import PlatformConfig
from oasis.governance.state_machine import LegislativeState

from .conftest import drive_to_deployed, execute_all_tasks


def test_full_lifecycle_synthetic(cross_db, producers):
    """Complete 3-branch pipeline in synthetic mode:
    legislate → deploy → route → commit → synthetic execute → validate → settle → rep update.
    """
    config = PlatformConfig(
        execution_mode="synthetic",
        synthetic_quality="perfect",
    )

    # Phase 1: Legislative — drive to DEPLOYED
    result = drive_to_deployed(cross_db, producers)
    assert result["sm"].current_state == LegislativeState.DEPLOYED

    # Phase 2 + 3: Execution + Adjudication
    settlements = execute_all_tasks(cross_db, result["session_id"], config)
    assert len(settlements) == 3

    # Verify all settlements succeeded with perfect quality
    for s in settlements:
        assert s.base_reward > 0
        assert s.final_reward > 0
        assert s.protocol_fee > 0
        assert s.insurance_fee > 0

    # Verify reputation was updated for all agents
    conn = sqlite3.connect(str(cross_db))
    conn.row_factory = sqlite3.Row
    rep_entries = conn.execute(
        "SELECT * FROM reputation_ledger WHERE reason = 'settlement'"
    ).fetchall()
    conn.close()

    assert len(rep_entries) == 3

    # Verify task statuses are all validated or beyond
    conn = sqlite3.connect(str(cross_db))
    conn.row_factory = sqlite3.Row
    tasks = conn.execute(
        "SELECT status FROM task_assignment WHERE session_id = ?",
        (result["session_id"],),
    ).fetchall()
    conn.close()

    for task in tasks:
        assert task["status"] in ("validated", "settled", "completed")
