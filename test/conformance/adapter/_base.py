"""Base class for per-contract adapters."""

from __future__ import annotations

from abc import ABC, abstractmethod

from test.conformance.oracle.schema import CallResult, FixtureCall


class AdapterBase(ABC):
    """One adapter per contract. Subclasses register their callables in registry.py."""

    contract: str = ""

    @abstractmethod
    def dispatch(self, call: FixtureCall) -> CallResult: ...
