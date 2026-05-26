"""Tests for the adapter registry and AdapterBase abstract class."""

from test.conformance.adapter._base import AdapterBase
from test.conformance.adapter.registry import CONTRACT_FN_MAP, lookup
from test.conformance.oracle.schema import (
    CallResult,
    CallResultPayload,
    FixtureCall,
)


class FakeAdapter(AdapterBase):
    contract = "FakeC"

    def dispatch(self, call: FixtureCall) -> CallResult:
        return CallResult(ok=True, revert=None, events=[], state_delta=[])


def test_registry_starts_empty_except_for_seeded_entries():
    # exact contents asserted in adapter-specific tasks
    assert isinstance(CONTRACT_FN_MAP, dict)


def test_lookup_returns_none_for_unknown_pair():
    assert lookup("UnknownC", "noSuchFn(uint256)") is None


def test_lookup_returns_adapter_for_registered_pair(monkeypatch):
    fa = FakeAdapter()
    bound = fa.dispatch
    monkeypatch.setitem(CONTRACT_FN_MAP, ("FakeC", "f(uint256)"), bound)
    assert lookup("FakeC", "f(uint256)") is bound


def test_adapter_base_dispatch_is_abstract():
    import pytest

    with pytest.raises(TypeError):
        AdapterBase().dispatch(
            FixtureCall(
                idx=0,
                target_contract="x",
                selector="0x0",
                function="f()",
                args=[],
                msg_sender="0x0",
                value_wei="0",
                result=CallResultPayload(kind="ok"),
            )
        )
