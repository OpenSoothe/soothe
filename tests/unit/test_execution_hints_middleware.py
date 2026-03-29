"""Unit tests for ExecutionHintsMiddleware."""

import pytest

from soothe.middleware.execution_hints import ExecutionHintsMiddleware


class TestExecutionHintsMiddleware:
    """Test ExecutionHintsMiddleware hint processing."""

    def test_extract_hints_all_present(self):
        """Test extracting all hints from config."""
        middleware = ExecutionHintsMiddleware()
        config = {
            "configurable": {
                "thread_id": "test-thread",
                "soothe_step_tools": ["glob", "grep"],
                "soothe_step_subagent": "browser",
                "soothe_step_expected_output": "Config file list",
            }
        }

        hints = middleware._extract_hints(config)

        assert hints is not None
        assert hints["tools"] == ["glob", "grep"]
        assert hints["subagent"] == "browser"
        assert hints["expected_output"] == "Config file list"

    def test_extract_hints_tools_only(self):
        """Test extracting only tools hint."""
        middleware = ExecutionHintsMiddleware()
        config = {
            "configurable": {
                "thread_id": "test-thread",
                "soothe_step_tools": ["read_file"],
            }
        }

        hints = middleware._extract_hints(config)

        assert hints is not None
        assert hints["tools"] == ["read_file"]
        assert hints["subagent"] is None
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
            "tools": ["glob", "grep"],
            "subagent": "browser",
            "expected_output": "Config file list",
        }

        text = middleware._format_hints(hints)

        assert "Suggested tools: glob, grep" in text
        assert "Suggested subagent: browser" in text
        assert "Expected output: Config file list" in text
        assert "Consider using the suggested approach first" in text

    def test_format_hints_missing_tools(self):
        """Test formatting hints without tools."""
        middleware = ExecutionHintsMiddleware()
        hints = {
            "tools": None,
            "subagent": "browser",
            "expected_output": "Config file list",
        }

        text = middleware._format_hints(hints)

        assert "Suggested tools" not in text
        assert "Suggested subagent: browser" in text
        assert "Expected output: Config file list" in text

    def test_format_hints_only_expected_output(self):
        """Test formatting with only expected output."""
        middleware = ExecutionHintsMiddleware()
        hints = {
            "tools": None,
            "subagent": None,
            "expected_output": "File contents",
        }

        text = middleware._format_hints(hints)

        assert "Expected output: File contents" in text
        assert "Suggested tools" not in text
        assert "Suggested subagent" not in text

    @pytest.mark.asyncio
    async def test_inject_hints_into_system_prompt(self):
        """Test injecting hints into agent state system prompt."""
        middleware = ExecutionHintsMiddleware()
        state = {"system_prompt": "You are Soothe agent."}
        config = {
            "configurable": {
                "thread_id": "test-thread",
                "soothe_step_tools": ["read_file"],
                "soothe_step_expected_output": "File contents",
            }
        }

        await middleware.process_agent_input(state, config)

        assert "Execution hints:" in state["system_prompt"]
        assert "Suggested tools: read_file" in state["system_prompt"]
        assert "Expected output: File contents" in state["system_prompt"]
        assert "execution_hints_received" in state

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

        await middleware.process_agent_input(state, config)

        assert state["system_prompt"] == original_prompt
        assert "execution_hints_received" not in state
