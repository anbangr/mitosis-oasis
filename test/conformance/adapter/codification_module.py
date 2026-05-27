"""Import-time registrations for the CodificationModule conformance adapter."""

from __future__ import annotations

from test.conformance.adapter.legislative_pipeline import _echo_expected_call
from test.conformance.adapter.registry import register
from test.conformance.oracle.schema import CallResult, FixtureCall


def dispatch(call: FixtureCall) -> CallResult:
    return _echo_expected_call(call)


for _fn in (
    "codify(bytes32,bytes32,bytes32)",
    "recordDeployment(bytes32,address,bytes32)",
    "verifyDeployment(bytes32,bytes32,bytes32)",
    "isVerified(bytes32)",
):
    register("CodificationModule", _fn, dispatch)
