"""Execution dispatcher — routes tasks to LLM agents or synthetic generator."""
from __future__ import annotations

import json
import sqlite3
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Union

from oasis.config import PlatformConfig
from oasis.execution.synthetic import SyntheticGenerator, SyntheticOutput
from oasis.execution.validator import OutputValidator, ValidationResult


@dataclass
class TaskStatus:
    """Current status of a task."""

    task_id: str
    status: str
    agent_did: str | None = None
    has_output: bool = False
    has_validation: bool = False


class ExecutionDispatcher:
    """Dispatch tasks for execution via LLM agents or synthetic generation.

    In **LLM mode**, the dispatcher transitions the task to 'executing' and
    waits for the agent to submit output via the API (``receive_output``).

    In **synthetic mode**, the dispatcher immediately generates output using
    ``SyntheticGenerator`` and stores it.
    """

    def __init__(
        self,
        config: PlatformConfig,
        db_path: Union[str, Path],
    ) -> None:
        self.config = config
        self.db_path = str(db_path)
        self.synthetic = SyntheticGenerator(config)
        self.validator = OutputValidator()

    def dispatch_task(self, task_id: str) -> dict:
        """Dispatch a committed task for execution.

        In LLM mode: transitions status to 'executing' (agent submits later).
        In synthetic mode: generates output, stores it, runs validation.

        Raises ValueError if task is not in 'committed' state.
        Returns a dict with dispatch result.
        """
        conn = self._connect()
        try:
            task = conn.execute(
                "SELECT * FROM task_assignment WHERE task_id = ?",
                (task_id,),
            ).fetchone()
            if task is None:
                raise ValueError(f"Task not found: {task_id}")
            if task["status"] != "committed":
                raise ValueError(
                    f"Task {task_id} is in state '{task['status']}'; "
                    "expected 'committed'"
                )

            # Transition to executing
            conn.execute(
                "UPDATE task_assignment SET status = 'executing' WHERE task_id = ?",
                (task_id,),
            )
            conn.commit()
        finally:
            conn.close()

        if self.config.execution_mode == "synthetic":
            task_dict = dict(task)
            output = self.synthetic.generate_output(task_dict)
            result = self._store_and_validate(task_id, output, task["agent_did"])
            return {
                "task_id": task_id,
                "mode": "synthetic",
                "status": result["status"],
                "validation": result.get("validation"),
            }

        # LLM mode: task stays in 'executing' until agent calls receive_output
        return {
            "task_id": task_id,
            "mode": "llm",
            "status": "executing",
        }

    def receive_output(
        self,
        task_id: str,
        output_data: str,
        agent_did: str,
    ) -> dict:
        """Receive output from an agent (LLM mode), store it, trigger validation.

        Raises ValueError if task is not in 'executing' state or agent mismatch.
        """
        conn = self._connect()
        try:
            task = conn.execute(
                "SELECT * FROM task_assignment WHERE task_id = ?",
                (task_id,),
            ).fetchone()
            if task is None:
                raise ValueError(f"Task not found: {task_id}")
            if task["status"] != "executing":
                raise ValueError(
                    f"Task {task_id} is in state '{task['status']}'; "
                    "expected 'executing'"
                )
            if task["agent_did"] != agent_did:
                raise ValueError(
                    f"Agent {agent_did} is not assigned to task {task_id}"
                )
        finally:
            conn.close()

        # Wrap as SyntheticOutput-like for storage
        output = SyntheticOutput(
            task_id=task_id,
            output_data=output_data,
            latency_ms=0,  # LLM mode doesn't track synthetic latency
            success=True,
        )
        return self._store_and_validate(task_id, output, agent_did)

    def get_task_status(self, task_id: str) -> TaskStatus:
        """Get current status of a task."""
        conn = self._connect()
        try:
            task = conn.execute(
                "SELECT * FROM task_assignment WHERE task_id = ?",
                (task_id,),
            ).fetchone()
            if task is None:
                raise ValueError(f"Task not found: {task_id}")

            has_output = conn.execute(
                "SELECT 1 FROM task_output WHERE task_id = ?",
                (task_id,),
            ).fetchone() is not None

            has_validation = conn.execute(
                "SELECT 1 FROM output_validation WHERE task_id = ?",
                (task_id,),
            ).fetchone() is not None

            return TaskStatus(
                task_id=task_id,
                status=task["status"],
                agent_did=task["agent_did"],
                has_output=has_output,
                has_validation=has_validation,
            )
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _store_and_validate(
        self,
        task_id: str,
        output: SyntheticOutput,
        agent_did: str,
    ) -> dict:
        """Store the output, run validation, and update task status."""
        conn = self._connect()
        try:
            # Store output
            output_id = f"out-{uuid.uuid4().hex[:8]}"
            conn.execute(
                "INSERT INTO task_output "
                "(output_id, task_id, agent_did, output_data, latency_ms) "
                "VALUES (?, ?, ?, ?, ?)",
                (output_id, task_id, agent_did, output.output_data, output.latency_ms),
            )
            conn.commit()
        finally:
            conn.close()

        # Run validation
        validation = self.validator.validate(
            task_id,
            {"output_data": output.output_data, "latency_ms": output.latency_ms},
            self.db_path,
        )

        # Update task status based on validation
        final_status = "completed" if (
            validation.schema_valid and validation.timeout_valid
        ) else "failed"

        conn = self._connect()
        try:
            conn.execute(
                "UPDATE task_assignment SET status = ? WHERE task_id = ?",
                (final_status, task_id),
            )
            conn.commit()
        finally:
            conn.close()

        return {
            "task_id": task_id,
            "output_id": output_id,
            "status": final_status,
            "validation": {
                "schema_valid": validation.schema_valid,
                "timeout_valid": validation.timeout_valid,
                "quality_score": validation.quality_score,
                "guardian_alert": validation.guardian_alert,
            },
        }

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.execute("PRAGMA foreign_keys = ON")
        conn.row_factory = sqlite3.Row
        return conn
