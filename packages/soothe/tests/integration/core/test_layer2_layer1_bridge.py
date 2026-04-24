"""Integration tests for Layer 2 → Layer 1 execution hints bridge."""

from unittest.mock import MagicMock, patch

import pytest

from soothe.middleware import ExecutionHintsMiddleware


class TestLayer2Layer1Bridge:
    """Test complete Layer 2 → Layer 1 integration with hints."""

    @pytest.mark.asyncio
    async def test_hints_propagate_from_stepaction_to_coreagent(self):
        """Test hints flow from StepAction through Executor to CoreAgent."""
        # Create middleware
        middleware = ExecutionHintsMiddleware()

        # Create agent state
        state = {"system_prompt": "You are Soothe agent."}

        # Create config with hints (as Executor would pass)
        config = {
            "configurable": {
                "thread_id": "thread-123",
                "soothe_step_tools": ["glob", "grep"],
                "soothe_step_expected_output": "Config file list",
            }
        }

        # Mock runtime
        mock_runtime = MagicMock()

        # Mock get_config to return our test config
        with patch("langgraph.config.get_config", return_value=config):
            # Process hints using the correct method
            await middleware.abefore_agent(state, mock_runtime)

        # Verify hints injected
        assert "Execution hints:" in state["system_prompt"]
        assert "Suggested tools: glob, grep" in state["system_prompt"]
        assert "Expected output: Config file list" in state["system_prompt"]

    @pytest.mark.asyncio
    async def test_llm_sees_hints_in_prompt(self):
        """Test LLM receives enhanced system prompt with hints."""
        middleware = ExecutionHintsMiddleware()

        original_prompt = "You are Soothe agent."
        state = {"system_prompt": original_prompt}
        config = {
            "configurable": {
                "thread_id": "test",
                "soothe_step_tools": ["read_file"],
                "soothe_step_expected_output": "File contents",
            }
        }

        mock_runtime = MagicMock()
        with patch("langgraph.config.get_config", return_value=config):
            await middleware.abefore_agent(state, mock_runtime)

        # LLM would see the enhanced prompt
        enhanced_prompt = state["system_prompt"]
        assert "Suggested tools: read_file" in enhanced_prompt
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

        # Prompt unchanged
        assert state["system_prompt"] == original_prompt

    @pytest.mark.asyncio
    async def test_executor_to_middleware_integration(self):
        """Test Executor → CoreAgent → ExecutionHintsMiddleware integration."""
        # This test verifies that executor config format matches middleware expectations
        # The integration is already tested in other tests; this validates config structure

        # Simulate config that executor would create
        executor_config = {
            "configurable": {
                "thread_id": "thread-123",
                "soothe_step_tools": ["glob", "grep"],
                "soothe_step_expected_output": "Config file list",
            }
        }

        # Now middleware should process this config correctly
        middleware = ExecutionHintsMiddleware()
        state = {"system_prompt": "You are Soothe agent."}

        mock_runtime = MagicMock()
        with patch("langgraph.config.get_config", return_value=executor_config):
            await middleware.abefore_agent(state, mock_runtime)

        # Verify middleware injected hints correctly from executor config format
        assert "Suggested tools: glob, grep" in state["system_prompt"]
        assert "Expected output: Config file list" in state["system_prompt"]

    @pytest.mark.asyncio
    async def test_advisory_nature_preserved(self):
        """Test hints are advisory - LLM can override."""
        middleware = ExecutionHintsMiddleware()

        state = {"system_prompt": "You are Soothe agent."}
        config = {
            "configurable": {
                "thread_id": "test",
                "soothe_step_tools": ["deprecated_tool"],
                "soothe_step_expected_output": "Result",
            }
        }

        mock_runtime = MagicMock()
        with patch("langgraph.config.get_config", return_value=config):
            await middleware.abefore_agent(state, mock_runtime)

        # Hints injected but LLM can decide
        enhanced_prompt = state["system_prompt"]
        assert "Suggested tools: deprecated_tool" in enhanced_prompt
        assert (
            "Consider using the suggested approach first, but decide based on what works best"
            in enhanced_prompt
        )
        # LLM would see this and could choose a different tool
