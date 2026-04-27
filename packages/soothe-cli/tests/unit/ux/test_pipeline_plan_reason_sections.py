"""Tests for agent-loop reasoned event with split assessment/plan reasoning."""

from soothe_cli.cli.stream import StreamDisplayPipeline
from soothe_cli.shared.essential_events import LOOP_REASON_EVENT_TYPE


def test_loop_agent_reason_emits_labeled_sections() -> None:
    """When plan_reasoning is set, emit judgement + plan reasoning lines."""
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
    }

    lines = pipeline.process(event)
    # IG-257: Only 2 lines (judgement + plan reasoning, assessment removed)
    assert len(lines) == 2
    assert "Run the test suite" in lines[0].content
    assert "Execute tests next" in lines[1].content
