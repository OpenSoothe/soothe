"""Integration tests for StrangeLoop execution hints (RFC-214).

Execution hints are delivered in the per-turn user message envelope
(``EXECUTION HINTS:`` section via ``UserMessageBuilder.build_execute_step_message``), not by mutating
``system_prompt``.
"""

from __future__ import annotations

from soothe.foundation.loop.prompts.user_message import UserMessageBuilder


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
    """RFC-214: hints in user envelope via UserMessageBuilder."""

    def test_envelope_includes_subagent_and_expected_output(self) -> None:
        """Executor-format hints appear inside EXECUTION HINTS: section."""
        hints = _execution_hints_text(subagent="tacitus", expected_output="Page summary")
        assert hints is not None
        builder = UserMessageBuilder()
        envelope = builder.build_execute_step_message(
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
        builder = UserMessageBuilder()
        envelope = builder.build_execute_step_message(
            "Read file",
            execution_hints=hints,
        )
        assert "EXECUTION HINTS:" in envelope
        assert "Expected output: File contents" in envelope
        assert "Suggested subagent:" not in envelope

    def test_envelope_omits_hints_block_when_empty(self) -> None:
        """No step metadata → no EXECUTION HINTS: section."""
        builder = UserMessageBuilder()
        envelope = builder.build_execute_step_message(
            "Plain step",
            execution_hints=None,
        )
        assert "EXECUTION HINTS:" not in envelope
        assert "GOAL:" in envelope
