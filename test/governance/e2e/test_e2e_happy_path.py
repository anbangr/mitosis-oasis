"""E2E happy path — full 6-stage legislative pipeline → DEPLOYED."""
from __future__ import annotations

from oasis.governance.state_machine import LegislativeState

from .conftest import drive_session_to_deployed


def test_full_pipeline_happy_path(e2e_db, producers):
    """5 producers + 4 clerks walk all stages to DEPLOYED."""
    result = drive_session_to_deployed(e2e_db, producers)

    sm = result["sm"]
    assert sm.current_state == LegislativeState.DEPLOYED

    # Verify history covers all expected transitions
    history = sm.history()
    states_visited = [h.to_state for h in history]
    assert LegislativeState.IDENTITY_VERIFICATION in states_visited
    assert LegislativeState.PROPOSAL_OPEN in states_visited
    assert LegislativeState.BIDDING_OPEN in states_visited
    assert LegislativeState.REGULATORY_REVIEW in states_visited
    assert LegislativeState.CODIFICATION in states_visited
    assert LegislativeState.AWAITING_APPROVAL in states_visited
    assert LegislativeState.DEPLOYED in states_visited

    # Artefacts present
    assert result["proposal_id"] is not None
    assert result["spec_id"] is not None
    assert len(result["approved_bids"]) > 0
