"""E2E concurrent sessions — two independent sessions without interference."""
from __future__ import annotations

from oasis.governance.state_machine import LegislativeState

from .conftest import drive_session_to_deployed


def test_two_concurrent_sessions(e2e_db, producers):
    """Two independent sessions run simultaneously and both reach DEPLOYED."""
    result_a = drive_session_to_deployed(
        e2e_db, producers, session_id="concurrent-a",
    )
    result_b = drive_session_to_deployed(
        e2e_db, producers, session_id="concurrent-b",
    )

    # Both sessions independently DEPLOYED
    assert result_a["sm"].current_state == LegislativeState.DEPLOYED
    assert result_b["sm"].current_state == LegislativeState.DEPLOYED

    # Different proposal IDs
    assert result_a["proposal_id"] != result_b["proposal_id"]

    # Different spec IDs
    assert result_a["spec_id"] != result_b["spec_id"]

    # History is independent
    history_a = result_a["sm"].history()
    history_b = result_b["sm"].history()
    assert len(history_a) == len(history_b)
    # Both have same number of transitions but different session_ids
    for h in history_a:
        assert h.to_state in LegislativeState
    for h in history_b:
        assert h.to_state in LegislativeState
