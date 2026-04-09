"""LLM interface — abstract protocol and mock implementation for testing.

Provides:
- LLMInterface protocol: abstract interface for LLM calls
- MockLLM: canned-response implementation for deterministic tests
- LLMError, LLMTimeoutError, LLMRateLimitError: error hierarchy
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


# ---------------------------------------------------------------------------
# Error hierarchy
# ---------------------------------------------------------------------------

class LLMError(Exception):
    """Base error for LLM operations."""


class LLMTimeoutError(LLMError):
    """LLM call timed out."""


class LLMRateLimitError(LLMError):
    """LLM rate limit exceeded."""


# ---------------------------------------------------------------------------
# Abstract interface
# ---------------------------------------------------------------------------

class LLMInterface(ABC):
    """Protocol for LLM calls used by Layer 2 reasoning."""

    @abstractmethod
    def query(self, prompt: str, context: dict | None = None) -> str:
        """Send a prompt (+optional context) and return the LLM response.

        Raises:
            LLMTimeoutError: if the call exceeds the timeout
            LLMRateLimitError: if the provider signals rate-limiting
            LLMError: for any other LLM-related failure
        """


# ---------------------------------------------------------------------------
# Mock implementation (for testing — no real API calls)
# ---------------------------------------------------------------------------

class MockLLM(LLMInterface):
    """Mock LLM that returns canned responses based on prompt keywords.

    Supports:
    - Keyword-based routing: if a keyword appears in the prompt, return
      the corresponding canned response.
    - Default response for unmatched prompts.
    - Error injection: set ``error_to_raise`` to simulate failures.
    """

    def __init__(
        self,
        responses: dict[str, str] | None = None,
        default_response: str = "No issues detected.",
        error_to_raise: LLMError | None = None,
    ) -> None:
        self._responses = responses or {}
        self._default = default_response
        self._error_to_raise = error_to_raise
        self.call_log: list[dict] = []  # track calls for assertions

    def query(self, prompt: str, context: dict | None = None) -> str:
        self.call_log.append({"prompt": prompt, "context": context})

        if self._error_to_raise is not None:
            raise self._error_to_raise

        prompt_lower = prompt.lower()
        for keyword, response in self._responses.items():
            if keyword.lower() in prompt_lower:
                return response

        return self._default
