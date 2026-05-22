"""Spec invariant SP-2: every task execution traverses the complete
seven-stage pipeline. No skips allowed.
"""

from __future__ import annotations


from oasis.execution.pipeline import (
    ExecutionStage,
    is_legal_advance,
    PIPELINE_ORDER,
)


def test_skipping_a_stage_is_rejected() -> None:
    for i, current in enumerate(PIPELINE_ORDER[:-2]):
        skip_target = PIPELINE_ORDER[i + 2]
        assert is_legal_advance(current, skip_target) is False, (
            f"SP-2 violated: {current.value} → {skip_target.value} not rejected"
        )


def test_full_pipeline_traversal_is_legal() -> None:
    """The legal full traversal exists end-to-end."""
    for current, nxt in zip(PIPELINE_ORDER[:-1], PIPELINE_ORDER[1:]):
        assert is_legal_advance(current, nxt) is True


def test_backward_stage_advance_is_rejected() -> None:
    """Moving backwards through the pipeline violates SP-2."""
    for current, prev in zip(PIPELINE_ORDER[1:], PIPELINE_ORDER[:-1]):
        assert is_legal_advance(current, prev) is False, (
            f"SP-2 violated: backward {current.value} → {prev.value} not rejected"
        )


def test_same_stage_advance_is_rejected() -> None:
    """Staying in the same stage is not a legal advance."""
    for stage in PIPELINE_ORDER:
        assert is_legal_advance(stage, stage) is False, (
            f"SP-2 violated: same-stage {stage.value} → {stage.value} not rejected"
        )


def test_record_has_no_legal_advance() -> None:
    """RECORD is terminal — no forward advance is legal."""
    for stage in PIPELINE_ORDER:
        if stage != ExecutionStage.RECORD:
            assert is_legal_advance(ExecutionStage.RECORD, stage) is False, (
                f"SP-2 violated: RECORD → {stage.value} should be illegal"
            )
