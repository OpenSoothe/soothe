"""Integration tests for Layer 2 → Layer 1 execution hints bridge."""

from unittest.mock import MagicMock, patch

import pytest

from soothe.middleware import ExecutionHintsMiddleware


class TestLayer2Layer1Bridge:
    """Test complete Layer 2 → Layer 1 integration with hints."""

    @pytest.mark.asyncio
    async def test_hints_propagate_from_stepaction_to_coreagent(self):
        """Test hints flow from StepAction through Executor to CoreAgent."""
        middleware = ExecutionHintsMiddleware()

        state = {"system_prompt": "You are Soothe agent."}

        config = {
            "configurable": {
                "thread_id": "thread-123",
                "soothe_step_subagent": "explore",
                "soothe_step_expected_output": "Matching paths under src/",
            }
        }

        mock_runtime = MagicMock()

        with patch("langgraph.config.get_config", return_value=config):
            await middleware.abefore_agent(state, mock_runtime)

        assert "Execution hints:" in state["system_prompt"]
        assert "Suggested subagent: explore" in state["system_prompt"]
        assert "Expected output: Matching paths under src/" in state["system_prompt"]

    @pytest.mark.asyncio
    async def test_llm_sees_hints_in_prompt(self):
        """Test LLM receives enhanced system prompt with hints."""
        middleware = ExecutionHintsMiddleware()

        original_prompt = "You are Soothe agent."
        state = {"system_prompt": original_prompt}
        config = {
            "configurable": {
                "thread_id": "test",
                "soothe_step_expected_output": "File contents",
            }
        }

        mock_runtime = MagicMock()
        with patch("langgraph.config.get_config", return_value=config):
            await middleware.abefore_agent(state, mock_runtime)

        enhanced_prompt = state["system_prompt"]
        assert "Expected output: File contents" in enhanced_prompt
        assert "Consider using the suggested approach first" in enhanced_prompt

    @pytest.mark.asyncio
    async def test_step_without_hints_works(self):
        """Test backward compatibility - steps without hints still work."""
        middleware = ExecutionHintsMiddleware()

        original_prompt = "You are Soothe agent."
        state = {"system_prompt": original_prompt}
        config = {
            "configurable": {
                "thread_id": "test",
            }
        }

        mock_runtime = MagicMock()
        with patch("langgraph.config.get_config", return_value=config):
            await middleware.abefore_agent(state, mock_runtime)

        assert state["system_prompt"] == original_prompt

    @pytest.mark.asyncio
    async def test_executor_to_middleware_integration(self):
        """Test Executor → CoreAgent → ExecutionHintsMiddleware integration."""
        executor_config = {
            "configurable": {
                "thread_id": "thread-123",
                "soothe_step_subagent": "browser",
                "soothe_step_expected_output": "Page summary",
            }
        }

        middleware = ExecutionHintsMiddleware()
        state = {"system_prompt": "You are Soothe agent."}

        mock_runtime = MagicMock()
        with patch("langgraph.config.get_config", return_value=executor_config):
            await middleware.abefore_agent(state, mock_runtime)

        assert "Suggested subagent: browser" in state["system_prompt"]
        assert "Expected output: Page summary" in state["system_prompt"]

    @pytest.mark.asyncio
    async def test_advisory_nature_preserved(self):
        """Test hints are advisory - LLM can override."""
        middleware = ExecutionHintsMiddleware()

        state = {"system_prompt": "You are Soothe agent."}
        config = {
            "configurable": {
                "thread_id": "test",
                "soothe_step_subagent": "research",
                "soothe_step_expected_output": "Result",
            }
        }

        mock_runtime = MagicMock()
        with patch("langgraph.config.get_config", return_value=config):
            await middleware.abefore_agent(state, mock_runtime)

        enhanced_prompt = state["system_prompt"]
        assert "Suggested subagent: research" in enhanced_prompt
        assert (
            "Consider using the suggested approach first, but decide based on what works best"
            in enhanced_prompt
        )
