"""P6 — Test BaseClerk abstract class."""
import pytest
from pathlib import Path

from oasis.governance.clerks.base import BaseClerk


class _ConcreteClerk(BaseClerk):
    """Concrete subclass for testing abstract BaseClerk."""

    def layer1_process(self, msg):
        return {"passed": True, "result": msg, "errors": []}


def test_authority_check_passes(governance_db: Path):
    """Clerk can perform actions within its authority envelope."""
    clerk = _ConcreteClerk(str(governance_db), "did:oasis:clerk-registrar")
    assert clerk.authority_check("registrar:open_session") is True


def test_authority_check_fails_wrong_role(governance_db: Path):
    """Clerk cannot perform actions outside its authority envelope."""
    clerk = _ConcreteClerk(str(governance_db), "did:oasis:clerk-registrar")
    # Registrar should not have speaker permissions
    assert clerk.authority_check("speaker:open_voting") is False


def test_abstract_methods_enforced():
    """Cannot instantiate BaseClerk directly."""
    with pytest.raises(TypeError):
        BaseClerk("fake.db", "did:test:clerk")
