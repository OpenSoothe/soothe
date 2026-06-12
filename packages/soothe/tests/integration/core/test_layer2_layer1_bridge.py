"""Integration tests for AgentLoop execution hints (RFC-214).

Execution hints are delivered in the per-turn user message envelope
(``EXECUTION HINTS:`` section via ``build_execute_step_envelope``), not by mutating
``system_prompt``. ``ExecutionHintsMiddleware.abefore_agent`` is a no-op kept
for stack compatibility.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from soothe.foundation.loop.prompts.user_envelope import build_execute_step_envelope
from soothe.middleware import ExecutionHintsMiddleware


def _execution_hints_text(*, subagent: str | None, expected_output: str | None) -> str | None:
    """Build the same hint string as ``executor.py`` (single-step and wave paths)."""
    hints_parts: list[str] = []
    if subagent:
        hints_parts.append(f"Suggested subagent: {subagent}")
    if expected_output:
        hints_parts.append(f"Expected output: {expected_output}")
    if not hints_parts:
        return None
    return ". ".join(hints_parts) + ". Consider using the suggested approach first."


class TestExecutionHintsEnvelopeIntegration:
    """RFC-214: hints in user envelope; middleware does not touch system prompt."""

    @pytest.mark.asyncio
    async def test_middleware_does_not_mutate_system_prompt_when_hints_in_config(self) -> None:
        """Configurable step hints do not flow through ExecutionHintsMiddleware."""
        middleware = ExecutionHintsMiddleware()
        original = "You are Soothe agent."
        state: dict[str, str] = {"system_prompt": original}
        config = {
            "configurable": {
                "thread_id": "thread-123",
                "soothe_step_subagent": "explore",
                "soothe_step_expected_output": "Matching paths under src/",
            }
        }
        mock_runtime = MagicMock()
        with patch("langgraph.config.get_config", return_value=config):
            result = await middleware.abefore_agent(state, mock_runtime)
        assert result is None
        assert state["system_prompt"] == original
        assert "Execution hints:" not in state["system_prompt"]

    @pytest.mark.asyncio
    async def test_middleware_preserves_prompt_without_step_hints(self) -> None:
        """No configurable hints → unchanged system prompt."""
        middleware = ExecutionHintsMiddleware()
        original = "You are Soothe agent."
        state: dict[str, str] = {"system_prompt": original}
        config = {"configurable": {"thread_id": "test"}}
        mock_runtime = MagicMock()
        with patch("langgraph.config.get_config", return_value=config):
            result = await middleware.abefore_agent(state, mock_runtime)
        assert result is None
        assert state["system_prompt"] == original

    def test_envelope_includes_subagent_and_expected_output(self) -> None:
        """Executor-format hints appear inside EXECUTION HINTS: section."""
        hints = _execution_hints_text(subagent="tacitus", expected_output="Page summary")
        assert hints is not None
        envelope = build_execute_step_envelope(
            "Open the page",
            execution_hints=hints,
        )
        assert "EXECUTION HINTS:" in envelope
        assert "Suggested subagent: tacitus" in envelope
        assert "Expected output: Page summary" in envelope
        assert "Consider using the suggested approach first" in envelope
        goal_idx = envelope.index("GOAL:")
        hints_idx = envelope.index("EXECUTION HINTS:")
        assert 0 <= goal_idx < hints_idx

    def test_envelope_expected_output_only(self) -> None:
        """Hints may omit subagent when only expected_output is set."""
        hints = _execution_hints_text(subagent=None, expected_output="File contents")
        assert hints is not None
        envelope = build_execute_step_envelope(
            "Read file",
            execution_hints=hints,
        )
        assert "EXECUTION HINTS:" in envelope
        assert "Expected output: File contents" in envelope
        assert "Suggested subagent:" not in envelope

    def test_envelope_omits_hints_block_when_empty(self) -> None:
        """No step metadata → no EXECUTION HINTS: section."""
        envelope = build_execute_step_envelope(
            "Plain step",
            execution_hints=None,
        )
        assert "EXECUTION HINTS:" not in envelope
        assert "GOAL:" in envelope
