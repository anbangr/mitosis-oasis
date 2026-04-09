"""Tests for routing rejection — non-DEPLOYED and missing decision."""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from oasis.execution.router import route_tasks


def test_non_deployed_rejected(execution_db: Path, producers: list[dict]) -> None:
    """Routing rejects a session that has not reached DEPLOYED state."""
    # Create a session in SESSION_INIT state
    conn = sqlite3.connect(str(execution_db))
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute(
        "INSERT INTO legislative_session (session_id, state, mission_budget_cap) "
        "VALUES ('sess-init', 'SESSION_INIT', 1000.0)"
    )
    conn.commit()
    conn.close()

    with pytest.raises(ValueError, match="expected DEPLOYED"):
        route_tasks("sess-init", execution_db)


def test_no_regulatory_decision_rejected(execution_db: Path) -> None:
    """Routing rejects a DEPLOYED session with no regulatory decision."""
    conn = sqlite3.connect(str(execution_db))
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute(
        "INSERT INTO legislative_session (session_id, state, mission_budget_cap) "
        "VALUES ('sess-empty', 'DEPLOYED', 1000.0)"
    )
    conn.commit()
    conn.close()

    with pytest.raises(ValueError, match="No regulatory decision"):
        route_tasks("sess-empty", execution_db)
