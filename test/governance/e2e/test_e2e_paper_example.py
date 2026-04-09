"""E2E paper example — replicate the 3-task mission trace from the paper."""
from __future__ import annotations

from oasis.governance.state_machine import LegislativeState

from .conftest import drive_session_to_deployed


def test_three_task_mission_trace(e2e_db, producers):
    """Replicate the 3-task mission trace from the AgentCity paper.

    Mission: coordinate → data collection → analysis
    This mirrors the example in Appendix B.8 of the paper.
    """
    paper_dag = {
        "nodes": [
            {
                "node_id": "mission-coord",
                "label": "Mission Coordinator",
                "service_id": "coordinator",
                "pop_tier": 1,
                "token_budget": 600.0,
                "timeout_ms": 60000,
            },
            {
                "node_id": "data-collect",
                "label": "Data Collection Agent",
                "service_id": "data-collector",
                "pop_tier": 1,
                "token_budget": 300.0,
                "timeout_ms": 60000,
            },
            {
                "node_id": "analysis",
                "label": "Analysis Agent",
                "service_id": "analyzer",
                "pop_tier": 1,
                "token_budget": 200.0,
                "timeout_ms": 60000,
            },
        ],
        "edges": [
            {"from_node_id": "mission-coord", "to_node_id": "data-collect"},
            {"from_node_id": "mission-coord", "to_node_id": "analysis"},
        ],
    }

    result = drive_session_to_deployed(
        e2e_db,
        producers,
        dag_spec=paper_dag,
        total_budget=1100.0,
    )

    sm = result["sm"]
    assert sm.current_state == LegislativeState.DEPLOYED

    # Verify the DAG structure was preserved in the proposal
    assert result["proposal_id"] is not None
    assert result["spec_id"] is not None

    # Verify all 3 task nodes got bids
    assert len(result["approved_bids"]) >= 3

    # Verify full state history
    history = sm.history()
    states = [h.to_state for h in history]
    expected = [
        LegislativeState.IDENTITY_VERIFICATION,
        LegislativeState.PROPOSAL_OPEN,
        LegislativeState.BIDDING_OPEN,
        LegislativeState.REGULATORY_REVIEW,
        LegislativeState.CODIFICATION,
        LegislativeState.AWAITING_APPROVAL,
        LegislativeState.DEPLOYED,
    ]
    assert states == expected
