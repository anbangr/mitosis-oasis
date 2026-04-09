"""E2E: Full 3-branch pipeline — legislate → execute (LLM) → settle → reputation."""
from __future__ import annotations

import sqlite3

from oasis.config import PlatformConfig
from oasis.governance.state_machine import LegislativeState

from .conftest import drive_to_deployed, execute_all_tasks_llm


def test_full_lifecycle_llm(cross_db, producers):
    """Complete 3-branch pipeline in LLM mode:
    legislate → deploy → route → commit → execute → validate → settle → rep update.
    """
    config = PlatformConfig(execution_mode="llm")

    # Phase 1: Legislative — drive to DEPLOYED
    result = drive_to_deployed(cross_db, producers)
    assert result["sm"].current_state == LegislativeState.DEPLOYED

    # Phase 2 + 3: Execution + Adjudication
    settlements = execute_all_tasks_llm(cross_db, result["session_id"], config)
    assert len(settlements) == 3  # 3 DAG nodes

    # Verify settlement properties
    for s in settlements:
        assert s.base_reward > 0
        assert s.final_reward > 0
        assert s.protocol_fee > 0
        assert s.insurance_fee > 0
        assert s.reputation_multiplier > 0

    # Verify reputation was updated
    conn = sqlite3.connect(str(cross_db))
    conn.execute("PRAGMA foreign_keys = ON")
    conn.row_factory = sqlite3.Row
    rep_entries = conn.execute(
        "SELECT * FROM reputation_ledger WHERE reason = 'settlement'"
    ).fetchall()
    conn.close()

    assert len(rep_entries) == 3  # One per settled task

    # Verify treasury has entries
    conn = sqlite3.connect(str(cross_db))
    conn.row_factory = sqlite3.Row
    treasury = conn.execute("SELECT * FROM treasury").fetchall()
    conn.close()

    # At least protocol_fee + insurance_fee per task = 6 entries minimum
    assert len(treasury) >= 6
