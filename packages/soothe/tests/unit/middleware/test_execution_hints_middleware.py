"""Unit tests for ExecutionHintsMiddleware (RFC-214: deprecated, hints in user envelope)."""

import pytest

from soothe.middleware import ExecutionHintsMiddleware


class TestExecutionHintsMiddleware:
    """Test ExecutionHintsMiddleware RFC-214 deprecation behavior."""

    @pytest.mark.asyncio
    async def test_abefore_agent_returns_none(self):
        """RFC-214: ExecutionHintsMiddleware.abefore_agent() is deprecated and returns None."""
        middleware = ExecutionHintsMiddleware()
        state = {"system_prompt": "You are Soothe agent."}
        config = {
            "configurable": {
                "thread_id": "test-thread",
                "soothe_step_subagent": "explore",
                "soothe_step_expected_output": "Config file list",
            }
        }

        from unittest.mock import patch

        with patch("langgraph.config.get_config", return_value=config):
            result = await middleware.abefore_agent(state, runtime=None)

        # RFC-214: Middleware no longer modifies system_prompt
        # Hints are built directly into user message envelope by executor
        assert result is None
        assert "Execution hints:" not in state["system_prompt"]

    @pytest.mark.asyncio
    async def test_no_injection_when_no_hints(self):
        """Test no injection when hints are absent."""
        middleware = ExecutionHintsMiddleware()
        original_prompt = "You are Soothe agent."
        state = {"system_prompt": original_prompt}
        config = {
            "configurable": {
                "thread_id": "test-thread",
            }
        }

        from unittest.mock import patch

        with patch("langgraph.config.get_config", return_value=config):
            result = await middleware.abefore_agent(state, runtime=None)

        assert state["system_prompt"] == original_prompt
        assert result is None
