"""Conflict-of-Interest (COI) recusal helper for adjudicators."""

from __future__ import annotations

import sqlite3


def is_conflicted(
    *,
    adjudicator_did: str,
    mission_id: str,
    agents_in_mission: set[str],
    gov_db_path: str,
) -> bool:
    """Return True if the adjudicator owns any agent in the mission.

    An adjudicator is conflicted when at least one agent participating in the
    mission has ``agent_registry.human_principal == adjudicator_did``.

    Parameters
    ----------
    adjudicator_did:
        The DID of the adjudicator to check.
    mission_id:
        The mission identifier (used for logging / context only).
    agents_in_mission:
        Set of agent DIDs that are part of the mission.
    gov_db_path:
        Filesystem path to the governance SQLite database.
    """
    if not agents_in_mission:
        return False

    placeholders = ",".join("?" for _ in agents_in_mission)
    sql = (
        f"SELECT COUNT(*) FROM agent_registry "
        f"WHERE agent_did IN ({placeholders}) AND human_principal = ?"
    )

    conn = sqlite3.connect(gov_db_path)
    try:
        cursor = conn.execute(sql, (*agents_in_mission, adjudicator_did))
        (count,) = cursor.fetchone()
        return count > 0
    finally:
        conn.close()
