"""P6 — Test Speaker.issue_approval."""
from pathlib import Path

from oasis.governance.clerks.speaker import Speaker


def test_signature_generated(governance_db: Path):
    """issue_approval generates a valid speaker signature."""
    sp = Speaker(str(governance_db), "did:oasis:clerk-speaker")
    result = sp.issue_approval("sess-approve", "spec-abc")
    assert result["speaker_signature"] is not None
    assert len(result["speaker_signature"]) == 64  # SHA-256 hex
    assert result["spec_id"] == "spec-abc"
    assert "timestamp" in result


def test_unauthorized_action_rejected(governance_db: Path):
    """Non-speaker clerk cannot issue approval."""
    # Use registrar DID — should fail authority check for speaker action
    sp = Speaker(str(governance_db), "did:oasis:clerk-registrar")
    result = sp.issue_approval("sess-approve", "spec-abc")
    assert result["speaker_signature"] is None
    assert "error" in result
    assert "unauthorized" in result["error"].lower() or "Unauthorized" in result["error"]
