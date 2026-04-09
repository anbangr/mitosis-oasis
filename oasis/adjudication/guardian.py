"""Guardian — alert pipeline for output validation failures and anomalies."""
from __future__ import annotations

import sqlite3
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Union

from oasis.config import PlatformConfig


@dataclass
class GuardianAlert:
    """Immutable representation of a guardian alert."""

    alert_id: str
    task_id: str
    alert_type: str
    severity: str
    details: str | None = None
    created_at: str | None = None


# Severity mapping: validation failure type → severity level
_SEVERITY_MAP = {
    "schema_failure": "CRITICAL",
    "timeout": "WARNING",
    "quality_below_threshold": "WARNING",
    "anomaly": "CRITICAL",
}


class Guardian:
    """Detection pipeline for output validation failures.

    Consumes ``ValidationResult`` objects from the execution validator
    and emits guardian alerts with appropriate severity levels.
    """

    def __init__(self, config: PlatformConfig, db_path: Union[str, Path]) -> None:
        self.config = config
        self.db_path = str(db_path)

    def process_validation(self, validation_result: dict) -> GuardianAlert | None:
        """Process a validation result and create a guardian alert if validation failed.

        Parameters
        ----------
        validation_result : dict
            Must contain: task_id, schema_valid, timeout_valid, quality_score.
            Mirrors the fields of ``ValidationResult``.

        Returns
        -------
        GuardianAlert | None
            The alert if one was created, else ``None`` for valid outputs.
        """
        task_id = validation_result["task_id"]

        if not validation_result.get("schema_valid", True):
            return self._emit_alert(task_id, "schema_failure", details="Schema validation failed")

        if not validation_result.get("timeout_valid", True):
            return self._emit_alert(task_id, "timeout", details="Timeout exceeded")

        quality = validation_result.get("quality_score", 1.0)
        if quality < 0.5:
            return self._emit_alert(
                task_id,
                "quality_below_threshold",
                details=f"quality_score={quality:.2f}",
            )

        # All checks passed — no alert
        return None

    def check_anomaly(self, task_id: str, output: Any) -> GuardianAlert | None:
        """Placeholder for dual-scorer anomaly detection.

        In v1 this is a no-op that always returns ``None``.
        Future versions will implement statistical anomaly detection
        comparing two independent quality scorers.
        """
        return None

    def get_alerts(
        self,
        *,
        severity: str | None = None,
        agent_did: str | None = None,
        task_id: str | None = None,
    ) -> list[GuardianAlert]:
        """Query guardian alerts with optional filters.

        Parameters
        ----------
        severity : str, optional
            Filter by severity level (e.g. "CRITICAL", "WARNING").
        agent_did : str, optional
            Filter by agent (via task_assignment join).
        task_id : str, optional
            Filter by task ID.
        """
        conn = self._connect()
        try:
            query = "SELECT ga.* FROM guardian_alert ga"
            conditions: list[str] = []
            params: list[str] = []

            if agent_did is not None:
                query += " JOIN task_assignment ta ON ga.task_id = ta.task_id"
                conditions.append("ta.agent_did = ?")
                params.append(agent_did)

            if severity is not None:
                conditions.append("ga.severity = ?")
                params.append(severity)

            if task_id is not None:
                conditions.append("ga.task_id = ?")
                params.append(task_id)

            if conditions:
                query += " WHERE " + " AND ".join(conditions)

            query += " ORDER BY ga.created_at DESC"

            rows = conn.execute(query, params).fetchall()
            return [
                GuardianAlert(
                    alert_id=r["alert_id"],
                    task_id=r["task_id"],
                    alert_type=r["alert_type"],
                    severity=r["severity"],
                    details=r["details"],
                    created_at=r["created_at"],
                )
                for r in rows
            ]
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _emit_alert(
        self,
        task_id: str,
        alert_type: str,
        *,
        details: str | None = None,
    ) -> GuardianAlert:
        """Write a guardian alert to the database and return it."""
        severity = _SEVERITY_MAP[alert_type]
        alert_id = f"alert-{uuid.uuid4().hex[:8]}"
        conn = self._connect()
        try:
            conn.execute(
                "INSERT INTO guardian_alert "
                "(alert_id, task_id, alert_type, severity, details) "
                "VALUES (?, ?, ?, ?, ?)",
                (alert_id, task_id, alert_type, severity, details),
            )
            conn.commit()
            return GuardianAlert(
                alert_id=alert_id,
                task_id=task_id,
                alert_type=alert_type,
                severity=severity,
                details=details,
            )
        finally:
            conn.close()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.execute("PRAGMA foreign_keys = ON")
        conn.row_factory = sqlite3.Row
        return conn
