"""E2E audit — verify all MSG1–MSG7 logged in correct order after happy path."""
from __future__ import annotations

from oasis.governance.messages import MessageType, get_session_messages
from oasis.governance.state_machine import LegislativeState

from .conftest import drive_session_to_deployed


def test_message_log_complete_and_ordered(e2e_db, producers):
    """After a happy-path deploy, all MSG1–MSG7 are logged in chronological order."""
    result = drive_session_to_deployed(e2e_db, producers)
    assert result["sm"].current_state == LegislativeState.DEPLOYED

    messages = get_session_messages(e2e_db, result["session_id"])

    # Extract protocol message types (exclude StateTransition and IdentityVerificationResponse)
    msg_types = [
        m["msg_type"] for m in messages
        if m["msg_type"] not in ("StateTransition", "IdentityVerificationResponse")
    ]

    # Expected message order (some may repeat for multiple agents/nodes):
    # MSG1 (IDENTITY_VERIFICATION_REQUEST)
    # MSG2 (IDENTITY_ATTESTATION) x N
    # MSG3 (DAG_PROPOSAL)
    # MSG4 (TASK_BID) x N
    # MSG5 (REGULATORY_DECISION)
    # MSG6 (CODED_CONTRACT_SPEC)
    # MSG7 (LEGISLATIVE_APPROVAL)

    # Check each type is present
    assert MessageType.IDENTITY_VERIFICATION_REQUEST.value in msg_types
    assert MessageType.IDENTITY_ATTESTATION.value in msg_types
    assert MessageType.DAG_PROPOSAL.value in msg_types
    assert MessageType.TASK_BID.value in msg_types
    assert MessageType.REGULATORY_DECISION.value in msg_types
    assert MessageType.CODED_CONTRACT_SPEC.value in msg_types
    assert MessageType.LEGISLATIVE_APPROVAL.value in msg_types

    # Verify ordering: first occurrence of each type must be in correct sequence
    type_order = [
        MessageType.IDENTITY_VERIFICATION_REQUEST.value,
        MessageType.IDENTITY_ATTESTATION.value,
        MessageType.DAG_PROPOSAL.value,
        MessageType.TASK_BID.value,
        MessageType.REGULATORY_DECISION.value,
        MessageType.CODED_CONTRACT_SPEC.value,
        MessageType.LEGISLATIVE_APPROVAL.value,
    ]

    first_indices = {}
    for idx, mt in enumerate(msg_types):
        if mt not in first_indices:
            first_indices[mt] = idx

    prev_idx = -1
    for mt in type_order:
        assert mt in first_indices, f"Message type {mt} not found in log"
        assert first_indices[mt] > prev_idx, (
            f"Message type {mt} at index {first_indices[mt]} "
            f"appears before expected (prev was {prev_idx})"
        )
        prev_idx = first_indices[mt]
