"""Output validation — schema checks, timeout checks, quality scoring, guardian alerts."""
from __future__ import annotations

import json
import sqlite3
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Union


@dataclass
class ValidationResult:
    """Result of validating a task output."""

    task_id: str
    schema_valid: bool
    timeout_valid: bool
    quality_score: float
    guardian_alert: str | None = None  # alert_id if emitted


class OutputValidator:
    """Validate task outputs against DAG node expectations.

    Checks:
    - Schema: output JSON has expected fields (task_id, result, status, metrics)
    - Timeout: latency_ms within DAG node timeout_ms
    - Quality: placeholder scorer (checks metrics if present)
    - Guardian alerts: written to guardian_alert table on failures
    """

    EXPECTED_OUTPUT_FIELDS = {"task_id", "result", "status"}
    QUALITY_THRESHOLD = 0.5

    def validate(
        self,
        task_id: str,
        output: dict,
        db_path: Union[str, Path],
    ) -> ValidationResult:
        """Run all validation checks on a task output.

        Parameters
        ----------
        task_id : str
            The task being validated.
        output : dict
            Must contain ``output_data`` (JSON string) and ``latency_ms``.
        db_path : str | Path
            Path to the SQLite database.

        Returns
        -------
        ValidationResult
        """
        conn = self._connect(db_path)
        try:
            # Parse output data
            try:
                output_data = json.loads(output["output_data"])
            except (json.JSONDecodeError, TypeError):
                output_data = {}

            # Look up expected schema from DAG node
            task = conn.execute(
                "SELECT node_id, session_id FROM task_assignment WHERE task_id = ?",
                (task_id,),
            ).fetchone()

            timeout_ms = None
            if task is not None:
                node = conn.execute(
                    "SELECT timeout_ms, output_schema FROM dag_node WHERE node_id = ?",
                    (task["node_id"],),
                ).fetchone()
                if node is not None:
                    timeout_ms = node["timeout_ms"]

            # Run checks
            schema_valid = self._check_schema(output_data)
            timeout_valid = self._check_timeout(
                output.get("latency_ms", 0), timeout_ms
            )
            quality_score = self._check_quality(output_data)

            # Emit guardian alerts for failures
            alert_id = None
            if not schema_valid:
                alert_id = self._emit_guardian_alert(
                    conn, task_id, "schema_failure", "CRITICAL"
                )
            elif not timeout_valid:
                alert_id = self._emit_guardian_alert(
                    conn, task_id, "timeout_exceeded", "WARNING"
                )
            elif quality_score < self.QUALITY_THRESHOLD:
                alert_id = self._emit_guardian_alert(
                    conn, task_id, "quality_below_threshold", "WARNING",
                    details=f"quality_score={quality_score:.2f}",
                )

            # Store validation record
            validation_id = f"val-{uuid.uuid4().hex[:8]}"
            conn.execute(
                "INSERT INTO output_validation "
                "(validation_id, task_id, schema_valid, timeout_valid, "
                "quality_score, guardian_alert_id) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (
                    validation_id,
                    task_id,
                    schema_valid,
                    timeout_valid,
                    quality_score,
                    alert_id,
                ),
            )
            conn.commit()

            return ValidationResult(
                task_id=task_id,
                schema_valid=schema_valid,
                timeout_valid=timeout_valid,
                quality_score=quality_score,
                guardian_alert=alert_id,
            )
        finally:
            conn.close()

    def _check_schema(self, output_data: dict) -> bool:
        """Check that the output contains expected fields."""
        if not isinstance(output_data, dict):
            return False
        return self.EXPECTED_OUTPUT_FIELDS.issubset(output_data.keys())

    def _check_timeout(
        self, latency_ms: int, timeout_ms: int | None
    ) -> bool:
        """Check that latency is within the node's timeout."""
        if timeout_ms is None:
            # No timeout constraint defined — pass
            return True
        return latency_ms <= timeout_ms

    def _check_quality(self, output_data: dict) -> float:
        """Placeholder quality scorer.

        If ``metrics`` is present with ``accuracy`` and ``completeness``,
        averages them.  Rejects clearly anomalous values (negative or > 1.5).
        Otherwise returns a neutral 0.7.
        """
        metrics = output_data.get("metrics") if isinstance(output_data, dict) else None
        if not isinstance(metrics, dict):
            return 0.7

        accuracy = metrics.get("accuracy")
        completeness = metrics.get("completeness")

        if accuracy is None or completeness is None:
            return 0.7

        # Reject clearly anomalous values
        try:
            accuracy = float(accuracy)
            completeness = float(completeness)
        except (TypeError, ValueError):
            return 0.0

        if accuracy < 0 or accuracy > 1.5 or completeness < 0 or completeness > 1.5:
            return 0.0

        return (accuracy + completeness) / 2.0

    def _emit_guardian_alert(
        self,
        conn: sqlite3.Connection,
        task_id: str,
        alert_type: str,
        severity: str,
        *,
        details: str | None = None,
    ) -> str:
        """Write a guardian alert and return its ID."""
        alert_id = f"alert-{uuid.uuid4().hex[:8]}"
        conn.execute(
            "INSERT INTO guardian_alert "
            "(alert_id, task_id, alert_type, severity, details) "
            "VALUES (?, ?, ?, ?, ?)",
            (alert_id, task_id, alert_type, severity, details),
        )
        return alert_id

    @staticmethod
    def _connect(db_path: Union[str, Path]) -> sqlite3.Connection:
        conn = sqlite3.connect(str(db_path))
        conn.execute("PRAGMA foreign_keys = ON")
        conn.row_factory = sqlite3.Row
        return conn
