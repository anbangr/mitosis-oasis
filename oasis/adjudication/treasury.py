"""Treasury — platform treasury accounting ledger."""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Union


@dataclass
class TreasuryEntry:
    """Single treasury ledger entry."""

    entry_id: int
    task_id: str | None
    agent_did: str | None
    entry_type: str
    amount: float
    balance_after: float
    created_at: str | None = None


@dataclass
class TreasurySummary:
    """Aggregated treasury summary."""

    inflows: dict[str, float] = field(default_factory=dict)
    outflows: dict[str, float] = field(default_factory=dict)
    net_balance: float = 0.0


class Treasury:
    """Platform treasury accounting.

    All monetary flows (protocol fees, insurance fees, slash proceeds,
    reputation subsidies) are recorded as append-only ledger entries
    with a running balance.
    """

    def __init__(self, db_path: Union[str, Path]) -> None:
        self.db_path = str(db_path)

    def record_fee(self, task_id: str, fee_type: str, amount: float) -> TreasuryEntry:
        """Record a fee inflow (protocol_fee or insurance_fee)."""
        conn = self._connect()
        try:
            balance = self._current_balance(conn) + amount
            conn.execute(
                "INSERT INTO treasury "
                "(task_id, entry_type, amount, balance_after) "
                "VALUES (?, ?, ?, ?)",
                (task_id, fee_type, amount, balance),
            )
            conn.commit()
            entry_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
            return TreasuryEntry(
                entry_id=entry_id,
                task_id=task_id,
                agent_did=None,
                entry_type=fee_type,
                amount=amount,
                balance_after=balance,
            )
        finally:
            conn.close()

    def record_slash(self, agent_did: str, amount: float) -> TreasuryEntry:
        """Record slash proceeds inflow."""
        conn = self._connect()
        try:
            balance = self._current_balance(conn) + amount
            conn.execute(
                "INSERT INTO treasury "
                "(agent_did, entry_type, amount, balance_after) "
                "VALUES (?, 'slash_proceeds', ?, ?)",
                (agent_did, amount, balance),
            )
            conn.commit()
            entry_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
            return TreasuryEntry(
                entry_id=entry_id,
                task_id=None,
                agent_did=agent_did,
                entry_type="slash_proceeds",
                amount=amount,
                balance_after=balance,
            )
        finally:
            conn.close()

    def record_subsidy(
        self, task_id: str, agent_did: str, amount: float
    ) -> TreasuryEntry:
        """Record a reputation subsidy outflow (negative amount)."""
        conn = self._connect()
        try:
            balance = self._current_balance(conn) - amount
            conn.execute(
                "INSERT INTO treasury "
                "(task_id, agent_did, entry_type, amount, balance_after) "
                "VALUES (?, ?, 'reputation_subsidy', ?, ?)",
                (task_id, agent_did, -amount, balance),
            )
            conn.commit()
            entry_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
            return TreasuryEntry(
                entry_id=entry_id,
                task_id=task_id,
                agent_did=agent_did,
                entry_type="reputation_subsidy",
                amount=-amount,
                balance_after=balance,
            )
        finally:
            conn.close()

    def get_balance(self) -> float:
        """Current treasury balance (inflows - outflows)."""
        conn = self._connect()
        try:
            return self._current_balance(conn)
        finally:
            conn.close()

    def get_summary(self) -> TreasurySummary:
        """Aggregate inflows by type, outflows by type, and net balance."""
        conn = self._connect()
        try:
            rows = conn.execute(
                "SELECT entry_type, SUM(amount) as total FROM treasury GROUP BY entry_type"
            ).fetchall()

            inflows: dict[str, float] = {}
            outflows: dict[str, float] = {}
            for r in rows:
                total = r["total"]
                if total >= 0:
                    inflows[r["entry_type"]] = total
                else:
                    outflows[r["entry_type"]] = abs(total)

            balance = self._current_balance(conn)
            return TreasurySummary(
                inflows=inflows,
                outflows=outflows,
                net_balance=balance,
            )
        finally:
            conn.close()

    def get_ledger(
        self,
        *,
        entry_type: str | None = None,
        task_id: str | None = None,
        agent_did: str | None = None,
    ) -> list[TreasuryEntry]:
        """Return treasury ledger entries with optional filters."""
        conn = self._connect()
        try:
            query = "SELECT * FROM treasury"
            conditions: list[str] = []
            params: list[str] = []

            if entry_type is not None:
                conditions.append("entry_type = ?")
                params.append(entry_type)
            if task_id is not None:
                conditions.append("task_id = ?")
                params.append(task_id)
            if agent_did is not None:
                conditions.append("agent_did = ?")
                params.append(agent_did)

            if conditions:
                query += " WHERE " + " AND ".join(conditions)
            query += " ORDER BY entry_id ASC"

            rows = conn.execute(query, params).fetchall()
            return [
                TreasuryEntry(
                    entry_id=r["entry_id"],
                    task_id=r["task_id"],
                    agent_did=r["agent_did"],
                    entry_type=r["entry_type"],
                    amount=r["amount"],
                    balance_after=r["balance_after"],
                    created_at=r["created_at"],
                )
                for r in rows
            ]
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _current_balance(self, conn: sqlite3.Connection) -> float:
        """Get the running balance from the latest treasury entry."""
        row = conn.execute(
            "SELECT balance_after FROM treasury ORDER BY entry_id DESC LIMIT 1"
        ).fetchone()
        return row["balance_after"] if row else 0.0

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.execute("PRAGMA foreign_keys = ON")
        conn.row_factory = sqlite3.Row
        return conn
