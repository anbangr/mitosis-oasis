"""P2 — Test LegislativeState enum and transition table."""
from oasis.governance.state_machine import (
    LegislativeState,
    TERMINAL_STATES,
    TRANSITIONS,
)


def test_all_9_states_defined():
    """Enum has exactly 9 members."""
    assert len(LegislativeState) == 9
    expected = {
        "SESSION_INIT", "IDENTITY_VERIFICATION", "PROPOSAL_OPEN",
        "BIDDING_OPEN", "REGULATORY_REVIEW", "CODIFICATION",
        "AWAITING_APPROVAL", "DEPLOYED", "FAILED",
    }
    assert {s.value for s in LegislativeState} == expected


def test_terminal_states():
    """DEPLOYED and FAILED are terminal — no outgoing transitions."""
    for state in TERMINAL_STATES:
        assert TRANSITIONS[state] == set()
    assert LegislativeState.DEPLOYED in TERMINAL_STATES
    assert LegislativeState.FAILED in TERMINAL_STATES
