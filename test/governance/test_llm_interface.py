"""P7 — LLM interface tests: MockLLM, error handling, real LLM skip."""
from __future__ import annotations

import pytest

from oasis.governance.clerks.llm_interface import (
    LLMError,
    LLMRateLimitError,
    LLMTimeoutError,
    MockLLM,
)


class TestMockLLMResponds:
    """MockLLM returns canned responses based on prompt keywords."""

    def test_keyword_routing(self):
        llm = MockLLM(responses={"sybil": "Possible Sybil attack detected."})
        result = llm.query("Analyze sybil patterns in session data.")
        assert result == "Possible Sybil attack detected."
        assert len(llm.call_log) == 1
        assert llm.call_log[0]["prompt"] == "Analyze sybil patterns in session data."

    def test_default_response(self):
        llm = MockLLM(default_response="All clear.")
        result = llm.query("Some unrelated prompt")
        assert result == "All clear."

    def test_context_passed_through(self):
        llm = MockLLM()
        ctx = {"session_id": "s1", "data": [1, 2, 3]}
        llm.query("test prompt", context=ctx)
        assert llm.call_log[0]["context"] == ctx


class TestRealLLMSkipped:
    """Real LLM integration is skipped without an API key."""

    @pytest.mark.skipif(True, reason="No real LLM API key configured")
    def test_real_llm_integration(self):
        # This test is always skipped — placeholder for real API integration
        pass


class TestLLMErrorHandling:
    """MockLLM error injection for timeout and rate limit."""

    def test_timeout_error(self):
        llm = MockLLM(error_to_raise=LLMTimeoutError("timed out"))
        with pytest.raises(LLMTimeoutError, match="timed out"):
            llm.query("any prompt")

    def test_rate_limit_error(self):
        llm = MockLLM(error_to_raise=LLMRateLimitError("rate limited"))
        with pytest.raises(LLMRateLimitError, match="rate limited"):
            llm.query("any prompt")

    def test_generic_llm_error(self):
        llm = MockLLM(error_to_raise=LLMError("generic failure"))
        with pytest.raises(LLMError, match="generic failure"):
            llm.query("any prompt")
