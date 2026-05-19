"""Tests for SanctionEngine slash stake 50/50 split routing.

Coverage target: ≥80% (100% on slash_stake).
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from oasis.adjudication.sanctions import SanctionEngine
from oasis.config import PlatformConfig


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _setup_agent_with_stake(
    db_path: Path, agent_did: str, locked_stake: float, total_balance: float
) -> None:
    """Insert or replace an agent with specific locked stake."""
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute(
        "INSERT OR IGNORE INTO agent_registry "
        "(agent_did, agent_type, display_name, human_principal, reputation_score) "
        "VALUES (?, 'producer', ?, 'human@example.com', 0.5)",
        (agent_did, agent_did),
    )
    conn.execute(
        "INSERT OR REPLACE INTO agent_balance "
        "(agent_did, total_balance, locked_stake, available_balance) "
        "VALUES (?, ?, ?, ?)",
        (agent_did, total_balance, locked_stake, total_balance - locked_stake),
    )
    conn.commit()
    conn.close()


def _get_treasury_sum_for_decision(db_path: Path, decision_id: str) -> float:
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        "SELECT SUM(amount) as s FROM treasury WHERE decision_id = ?",
        (decision_id,),
    ).fetchone()
    conn.close()
    return row["s"] if row and row["s"] is not None else 0.0


def _get_insurance_sum_for_decision(db_path: Path, decision_id: str) -> float:
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        "SELECT SUM(amount) as s FROM insurance_pool WHERE decision_id = ?",
        (decision_id,),
    ).fetchone()
    conn.close()
    return row["s"] if row and row["s"] is not None else 0.0


# ---------------------------------------------------------------------------
# Spec tests
# ---------------------------------------------------------------------------


def test_full_slash_splits_50_50(
    adjudication_db: Path, config: PlatformConfig
) -> None:
    """T1: Full 100-unit slash splits 50/50 between treasury and insurance_pool."""
    engine = SanctionEngine(config)
    agent_did = "did:adj:agent-full"
    _setup_agent_with_stake(adjudication_db, agent_did, 100.0, 100.0)

    decision = engine.slash_stake(agent_did, 100.0, "full slash", adjudication_db)

    treasury_sum = _get_treasury_sum_for_decision(
        adjudication_db, decision.decision_id
    )
    insurance_sum = _get_insurance_sum_for_decision(
        adjudication_db, decision.decision_id
    )

    assert treasury_sum == pytest.approx(50.0)
    assert insurance_sum == pytest.approx(50.0)


def test_partial_slash_splits_50_50(
    adjudication_db: Path, config: PlatformConfig
) -> None:
    """T2: Partial slash also splits 50/50 of actual_slash."""
    engine = SanctionEngine(config)
    agent_did = "did:adj:agent-partial"
    _setup_agent_with_stake(adjudication_db, agent_did, 40.0, 100.0)

    decision = engine.slash_stake(agent_did, 100.0, "partial slash", adjudication_db)

    treasury_sum = _get_treasury_sum_for_decision(
        adjudication_db, decision.decision_id
    )
    insurance_sum = _get_insurance_sum_for_decision(
        adjudication_db, decision.decision_id
    )

    assert treasury_sum == pytest.approx(20.0)
    assert insurance_sum == pytest.approx(20.0)


def test_agent_balance_debited_by_actual_slash(
    adjudication_db: Path, config: PlatformConfig
) -> None:
    """T3: Agent balance debited by full actual_slash."""
    engine = SanctionEngine(config)
    agent_did = "did:adj:agent-debit"
    _setup_agent_with_stake(adjudication_db, agent_did, 100.0, 100.0)

    engine.slash_stake(agent_did, 100.0, "debit test", adjudication_db)

    conn = sqlite3.connect(str(adjudication_db))
    conn.row_factory = sqlite3.Row
    bal = conn.execute(
        "SELECT locked_stake, total_balance FROM agent_balance WHERE agent_did = ?",
        (agent_did,),
    ).fetchone()
    conn.close()

    assert bal["locked_stake"] == pytest.approx(0.0)
    assert bal["total_balance"] == pytest.approx(0.0)


def test_fp_exactness_invariant(
    adjudication_db: Path, config: PlatformConfig
) -> None:
    """T5: treasury + insurance_pool sums equal actual_slash exactly for the decision_id."""
    engine = SanctionEngine(config)
    agent_did = "did:adj:agent-fp"
    _setup_agent_with_stake(adjudication_db, agent_did, 33.33, 100.0)

    decision = engine.slash_stake(agent_did, 33.33, "fp test", adjudication_db)

    treasury_sum = _get_treasury_sum_for_decision(
        adjudication_db, decision.decision_id
    )
    insurance_sum = _get_insurance_sum_for_decision(
        adjudication_db, decision.decision_id
    )

    # Should equal actual_slash exactly (no float drift)
    assert treasury_sum + insurance_sum == pytest.approx(33.33)


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


def test_zero_slash_no_rows_inserted(
    adjudication_db: Path, config: PlatformConfig
) -> None:
    """Edge: Slash request equal to zero — no rows inserted into either ledger."""
    engine = SanctionEngine(config)
    agent_did = "did:adj:agent-zero"
    _setup_agent_with_stake(adjudication_db, agent_did, 10.0, 100.0)

    engine.slash_stake(agent_did, 0.0, "zero slash", adjudication_db)

    conn = sqlite3.connect(str(adjudication_db))
    conn.row_factory = sqlite3.Row
    t_row = conn.execute(
        "SELECT COUNT(*) as c FROM treasury WHERE agent_did = ?",
        (agent_did,),
    ).fetchone()
    i_row = conn.execute(
        "SELECT COUNT(*) as c FROM insurance_pool WHERE agent_did = ?",
        (agent_did,),
    ).fetchone()
    conn.close()

    assert t_row["c"] == 0
    assert i_row["c"] == 0


def test_odd_valued_slash_splits_evenly(
    adjudication_db: Path, config: PlatformConfig
) -> None:
    """Edge: Odd-valued slash (7.0) splits evenly; sum equals 7.0 exactly."""
    engine = SanctionEngine(config)
    agent_did = "did:adj:agent-odd"
    _setup_agent_with_stake(adjudication_db, agent_did, 7.0, 100.0)

    decision = engine.slash_stake(agent_did, 7.0, "odd slash", adjudication_db)

    treasury_sum = _get_treasury_sum_for_decision(
        adjudication_db, decision.decision_id
    )
    insurance_sum = _get_insurance_sum_for_decision(
        adjudication_db, decision.decision_id
    )

    assert treasury_sum == pytest.approx(3.5)
    assert insurance_sum == pytest.approx(3.5)
    assert treasury_sum + insurance_sum == pytest.approx(7.0)


def test_repeated_slashes_cumulative_balance(
    adjudication_db: Path, config: PlatformConfig
) -> None:
    """Edge: Repeated slashes on the same agent write cumulative balance_after."""
    engine = SanctionEngine(config)
    agent_did = "did:adj:agent-repeat"
    _setup_agent_with_stake(adjudication_db, agent_did, 30.0, 100.0)

    decision1 = engine.slash_stake(agent_did, 10.0, "first slash", adjudication_db)
    decision2 = engine.slash_stake(agent_did, 10.0, "second slash", adjudication_db)

    conn = sqlite3.connect(str(adjudication_db))
    conn.row_factory = sqlite3.Row
    t1 = conn.execute(
        "SELECT balance_after FROM treasury WHERE decision_id = ?",
        (decision1.decision_id,),
    ).fetchone()
    t2 = conn.execute(
        "SELECT balance_after FROM treasury WHERE decision_id = ?",
        (decision2.decision_id,),
    ).fetchone()
    i1 = conn.execute(
        "SELECT balance_after FROM insurance_pool WHERE decision_id = ?",
        (decision1.decision_id,),
    ).fetchone()
    i2 = conn.execute(
        "SELECT balance_after FROM insurance_pool WHERE decision_id = ?",
        (decision2.decision_id,),
    ).fetchone()
    conn.close()

    # Each slash is 10.0 → 5.0 to treasury, 5.0 to insurance_pool per slash
    assert t1["balance_after"] == pytest.approx(5.0)
    assert t2["balance_after"] == pytest.approx(10.0)
    assert i1["balance_after"] == pytest.approx(5.0)
    assert i2["balance_after"] == pytest.approx(10.0)


def test_slash_larger_than_locked_stake_splits_50_50(
    adjudication_db: Path, config: PlatformConfig
) -> None:
    """Edge: Slash request larger than locked stake — actual_slash capped; split still 50/50."""
    engine = SanctionEngine(config)
    agent_did = "did:adj:agent-big"
    _setup_agent_with_stake(adjudication_db, agent_did, 15.0, 100.0)

    decision = engine.slash_stake(agent_did, 999.0, "big slash", adjudication_db)

    treasury_sum = _get_treasury_sum_for_decision(
        adjudication_db, decision.decision_id
    )
    insurance_sum = _get_insurance_sum_for_decision(
        adjudication_db, decision.decision_id
    )

    assert treasury_sum == pytest.approx(7.5)
    assert insurance_sum == pytest.approx(7.5)
