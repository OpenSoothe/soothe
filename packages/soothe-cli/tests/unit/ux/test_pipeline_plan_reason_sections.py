"""Tests for agent-loop reasoned event with split assessment/plan reasoning."""

from soothe_cli.cli.stream import StreamDisplayPipeline
from soothe_cli.shared.essential_events import LOOP_REASON_EVENT_TYPE


def test_loop_agent_reason_emits_labeled_sections() -> None:
    """When assessment_reasoning and plan_reasoning are set, emit three lines."""
    pipeline = StreamDisplayPipeline(verbosity="normal")

    event = {
        "type": LOOP_REASON_EVENT_TYPE,
        "next_action": "Run the test suite",
        "status": "continue",
        "confidence": 0.8,
        "iteration": 1,
        "plan_action": "new",
        "assessment_reasoning": "Evidence is accumulating.",
        "plan_reasoning": "Execute tests next.",
        "reasoning": "Evidence is accumulating. [Plan] Execute tests next.",
    }

    lines = pipeline.process(event)
    assert len(lines) == 3
    assert "[new]" in lines[0].content
    assert "Assessment:" in lines[1].content
    assert "Evidence is accumulating" in lines[1].content
    assert "Plan:" in lines[2].content
    assert "Execute tests next" in lines[2].content


def test_loop_agent_reason_legacy_reasoning_only() -> None:
    """Without structured fields, fall back to a single reasoning line."""
    pipeline = StreamDisplayPipeline(verbosity="normal")

    event = {
        "type": LOOP_REASON_EVENT_TYPE,
        "next_action": "Continue work",
        "status": "continue",
        "confidence": 0.8,
        "iteration": 0,
        "reasoning": "Legacy combined text",
        "assessment_reasoning": "",
        "plan_reasoning": "",
    }

    lines = pipeline.process(event)
    assert len(lines) == 2
    assert "Legacy combined text" in lines[1].content
