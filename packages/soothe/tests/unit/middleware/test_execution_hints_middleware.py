"""Unit tests for ExecutionHintsMiddleware."""

import pytest

from soothe.middleware import ExecutionHintsMiddleware


class TestExecutionHintsMiddleware:
    """Test ExecutionHintsMiddleware hint processing."""

    def test_extract_hints_all_present(self):
        """Test extracting all hints from config."""
        middleware = ExecutionHintsMiddleware()
        config = {
            "configurable": {
                "thread_id": "test-thread",
                "soothe_step_subagent": "browser",
                "soothe_step_expected_output": "Config file list",
            }
        }

        hints = middleware._extract_hints(config)

        assert hints is not None
        assert hints["subagent"] == "browser"
        assert hints["expected_output"] == "Config file list"

    def test_extract_hints_subagent_only(self):
        """Test extracting only subagent hint."""
        middleware = ExecutionHintsMiddleware()
        config = {
            "configurable": {
                "thread_id": "test-thread",
                "soothe_step_subagent": "explore",
            }
        }

        hints = middleware._extract_hints(config)

        assert hints is not None
        assert hints["subagent"] == "explore"
        assert hints["expected_output"] is None

    def test_extract_hints_none_present(self):
        """Test when no hints are present."""
        middleware = ExecutionHintsMiddleware()
        config = {
            "configurable": {
                "thread_id": "test-thread",
            }
        }

        hints = middleware._extract_hints(config)

        assert hints is None

    def test_extract_hints_empty_configurable(self):
        """Test when configurable is empty."""
        middleware = ExecutionHintsMiddleware()
        config = {}

        hints = middleware._extract_hints(config)

        assert hints is None

    def test_format_hints_all_present(self):
        """Test formatting all hints."""
        middleware = ExecutionHintsMiddleware()
        hints = {
            "subagent": "browser",
            "expected_output": "Config file list",
        }

        text = middleware._format_hints(hints)

        assert "Suggested subagent: browser" in text
        assert "Expected output: Config file list" in text
        assert "Consider using the suggested approach first" in text

    def test_format_hints_missing_subagent(self):
        """Test formatting hints without subagent."""
        middleware = ExecutionHintsMiddleware()
        hints = {
            "subagent": None,
            "expected_output": "Config file list",
        }

        text = middleware._format_hints(hints)

        assert "Suggested subagent" not in text
        assert "Expected output: Config file list" in text

    def test_format_hints_only_expected_output(self):
        """Test formatting with only expected output."""
        middleware = ExecutionHintsMiddleware()
        hints = {
            "subagent": None,
            "expected_output": "File contents",
        }

        text = middleware._format_hints(hints)

        assert "Expected output: File contents" in text
        assert "Suggested subagent" not in text

    @pytest.mark.asyncio
    async def test_inject_hints_into_system_prompt(self):
        """Test injecting hints into agent state system prompt."""
        middleware = ExecutionHintsMiddleware()
        state = {"system_prompt": "You are Soothe agent."}
        config = {
            "configurable": {
                "thread_id": "test-thread",
                "soothe_step_subagent": "explore",
                "soothe_step_expected_output": "File contents",
            }
        }

        from unittest.mock import patch

        with patch("langgraph.config.get_config", return_value=config):
            result = await middleware.abefore_agent(state, runtime=None)

        assert "Execution hints:" in state["system_prompt"]
        assert "Suggested subagent: explore" in state["system_prompt"]
        assert "Expected output: File contents" in state["system_prompt"]
        assert result is not None
        assert "execution_hints_received" in result

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
