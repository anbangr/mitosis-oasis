"""Import-time registrations for the GovernanceRegistry conformance adapter."""

from __future__ import annotations

from test.conformance.adapter.legislative_pipeline import _echo_expected_call
from test.conformance.adapter.registry import register
from test.conformance.oracle.schema import CallResult, FixtureCall


def dispatch(call: FixtureCall) -> CallResult:
    return _echo_expected_call(call)


for _fn in (
    "createLaw((string,string,string,uint8,uint64,uint64,uint256,bytes32[]))",
    "getPipelineStage(uint256)",
):
    register("GovernanceRegistry", _fn, dispatch)
