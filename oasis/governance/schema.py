"""Governance SQLite schema — 15 tables for the legislative protocol.

Created in P1.  This stub provides the function signatures so that test
fixtures (P0) can import them; the DDL is filled in during P1.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Union


# ---------------------------------------------------------------------------
# Table creation
# ---------------------------------------------------------------------------

def create_governance_tables(db_path: Union[str, Path]) -> None:
    """Create all 15 governance tables.  Idempotent (IF NOT EXISTS)."""
    raise NotImplementedError("P1: governance schema not yet implemented")


# ---------------------------------------------------------------------------
# Seed helpers
# ---------------------------------------------------------------------------

def seed_constitution(db_path: Union[str, Path]) -> None:
    """Insert default constitutional parameters from the paper."""
    raise NotImplementedError("P1: constitution seeding not yet implemented")


def seed_clerks(db_path: Union[str, Path]) -> None:
    """Register the 4 clerk agents with authority envelopes."""
    raise NotImplementedError("P1: clerk seeding not yet implemented")
