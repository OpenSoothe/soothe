"""Integration tests for StrangeLoop execution guidance (RFC-214).

Execution guidance is delivered in the per-turn user message envelope
(``EXPECTED OUTPUT`` / ``INSTRUCTIONS`` via ``UserMessageBuilder.build_execute_step_message``),
not by mutating ``system_prompt``.
"""

from __future__ import annotations

from soothe.sloop.engine.step_predecessor_context import (
    ExecuteStepEnvelopeBody,
    build_dependent_execution_hints,
)
from soothe.sloop.prompts.user_message import UserMessageBuilder
from soothe.sloop.state.schemas import StepAction


def _envelope_body(*, subagent: str | None, expected_output: str | None) -> ExecuteStepEnvelopeBody:
    """Build the same guidance as ``executor.py`` for a root step without dependencies."""
    return build_dependent_execution_hints(
        StepAction(id="01", description="Step"),
        has_predecessor_evidence=False,
        wire_subagent=subagent,
        workspace=None,
        expected_output=expected_output,
    )


class TestExecutionGuidanceEnvelopeIntegration:
    """RFC-214: guidance in user envelope via UserMessageBuilder."""

    def test_envelope_includes_subagent_and_expected_output(self) -> None:
        """Executor-format guidance appears in EXPECTED OUTPUT and INSTRUCTIONS sections."""
        body = _envelope_body(subagent="deep_research", expected_output="Page summary")
        builder = UserMessageBuilder()
        envelope = builder.build_execute_step_message(
            "Open the page",
            step_id="01",
            short_description="Open the page",
            expected_output=body.expected_output,
            instructions=body.instructions,
        )
        assert "EXECUTION HINTS:" not in envelope
        assert "EXPECTED OUTPUT:" in envelope
        assert "INSTRUCTIONS:" in envelope
        assert "Suggested subagent: deep_research" in envelope
        assert "Page summary" in envelope
        assert "EXECUTION METADATA:" in envelope
        assert "step_id: 01" in envelope
        task_idx = envelope.index("EXECUTION TASK:")
        expected_idx = envelope.index("EXPECTED OUTPUT:")
        instructions_idx = envelope.index("INSTRUCTIONS:")
        metadata_idx = envelope.index("EXECUTION METADATA:")
        assert task_idx < expected_idx < instructions_idx < metadata_idx

    def test_envelope_expected_output_only(self) -> None:
        """Guidance may omit subagent when only expected_output is set."""
        body = _envelope_body(subagent=None, expected_output="File contents")
        builder = UserMessageBuilder()
        envelope = builder.build_execute_step_message(
            "Read file",
            expected_output=body.expected_output,
            instructions=body.instructions,
        )
        assert "EXECUTION HINTS:" not in envelope
        assert "EXPECTED OUTPUT:" in envelope
        assert "File contents" in envelope
        assert "Suggested subagent:" not in envelope

    def test_envelope_omits_guidance_sections_when_empty(self) -> None:
        """No step metadata → no EXPECTED OUTPUT or INSTRUCTIONS sections."""
        builder = UserMessageBuilder()
        envelope = builder.build_execute_step_message(
            "Plain step",
        )
        assert "EXECUTION HINTS:" not in envelope
        assert "EXPECTED OUTPUT:" not in envelope
        assert "INSTRUCTIONS:" not in envelope
        assert "EXECUTION TASK:" in envelope
