"""Spec exec §7: τ_anchor default 10s (small DAGs) / 60s (large DAGs).
Constitutional parameter."""
import sqlite3
from pathlib import Path

import pytest

from oasis.governance.schema import create_governance_tables, seed_constitution


def test_tau_anchor_small_seeded_to_10(tmp_path):
    p = tmp_path / "g.db"
    create_governance_tables(str(p))
    seed_constitution(str(p))
    conn = sqlite3.connect(str(p))
    row = conn.execute(
        "SELECT param_value FROM constitution "
        "WHERE param_name = 'tau_anchor_small_seconds'"
    ).fetchone()
    assert row[0] == 10.0


def test_tau_anchor_large_seeded_to_60(tmp_path):
    p = tmp_path / "g.db"
    create_governance_tables(str(p))
    seed_constitution(str(p))
    conn = sqlite3.connect(str(p))
    row = conn.execute(
        "SELECT param_value FROM constitution "
        "WHERE param_name = 'tau_anchor_large_seconds'"
    ).fetchone()
    assert row[0] == 60.0
