"""Unit tests for LLMTracingMiddleware response logging."""

from __future__ import annotations

import logging
from types import SimpleNamespace

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from soothe.middleware.llm_tracing import LLMTracingMiddleware


class TestLLMTracingMiddleware:
    """Test compact response log formatting."""

    def test_log_response_includes_ai_message_type(self, caplog):
        """Response summary includes AIMessage class name."""
        middleware = LLMTracingMiddleware()
        response = SimpleNamespace(
            result=[
                HumanMessage(content="hi"),
                AIMessage(content="hello"),
            ]
        )

        with caplog.at_level(logging.DEBUG, logger="soothe.middleware.llm_tracing"):
            middleware._log_response(trace_id=18, response=response, duration_ms=1234)

        assert "message_type': 'AIMessage'" in caplog.text

    def test_log_response_fallback_includes_last_message_type(self, caplog):
        """Fallback summary includes last non-AI message class name."""
        middleware = LLMTracingMiddleware()
        response = SimpleNamespace(
            result=[
                HumanMessage(content="request"),
                SystemMessage(content="policy"),
            ]
        )

        with caplog.at_level(logging.DEBUG, logger="soothe.middleware.llm_tracing"):
            middleware._log_response(trace_id=19, response=response, duration_ms=987)

        assert "message_type': 'SystemMessage'" in caplog.text
        assert "error': 'no AI message'" in caplog.text
