"""Integration tests for Layer 2 → Layer 1 execution hints bridge."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from soothe.cognition.loop_agent.executor import Executor
from soothe.cognition.loop_agent.schemas import AgentDecision, StepAction
from soothe.middleware.execution_hints import ExecutionHintsMiddleware


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

        # Process hints
        await middleware.process_agent_input(state, config)

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

        await middleware.process_agent_input(state, config)

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

        await middleware.process_agent_input(state, config)

        # Prompt unchanged
        assert state["system_prompt"] == original_prompt

    @pytest.mark.asyncio
    async def test_executor_to_middleware_integration(self):
        """Test Executor → CoreAgent → ExecutionHintsMiddleware integration."""
        # Mock CoreAgent
        mock_agent = MagicMock()
        captured_config = None

        async def capture_astream(input_msg, config):
            nonlocal captured_config
            captured_config = config
            return iter([])

        mock_agent.astream = capture_astream

        # Create executor
        executor = Executor(mock_agent)

        # Create step with hints
        step = StepAction(
            id="step-1",
            description="Find config files",
            tools=["glob", "grep"],
            expected_output="Config file list",
        )

        # Execute step
        await executor._execute_step(step, "thread-123")

        # Verify hints passed in config
        assert captured_config is not None
        assert captured_config["configurable"]["soothe_step_tools"] == ["glob", "grep"]
        assert captured_config["configurable"]["soothe_step_expected_output"] == "Config file list"

        # Now middleware would process this config
        middleware = ExecutionHintsMiddleware()
        state = {"system_prompt": "You are Soothe agent."}

        await middleware.process_agent_input(state, captured_config)

        # Verify middleware injected hints
        assert "Suggested tools: glob, grep" in state["system_prompt"]

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

        await middleware.process_agent_input(state, config)

        # Hints injected but LLM can decide
        enhanced_prompt = state["system_prompt"]
        assert "Suggested tools: deprecated_tool" in enhanced_prompt
        assert "Consider using the suggested approach first, but decide based on what works best" in enhanced_prompt
        # LLM would see this and could choose a different tool
