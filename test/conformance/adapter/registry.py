"""Function-level adapter registry.

A `(contract_name, "function(types)")` pair maps to a callable
`(FixtureCall) -> CallResult`. Missing pairs are reported as GAP by the harness.
"""

from __future__ import annotations

from typing import Callable

from test.conformance.oracle.schema import CallResult, FixtureCall


AdapterFn = Callable[[FixtureCall], CallResult]


CONTRACT_FN_MAP: dict[tuple[str, str], AdapterFn] = {}


def lookup(contract: str, function: str) -> AdapterFn | None:
    return CONTRACT_FN_MAP.get((contract, function))


def register(contract: str, function: str, fn: AdapterFn) -> None:
    """Used by per-contract adapter modules at import time."""
    CONTRACT_FN_MAP[(contract, function)] = fn
