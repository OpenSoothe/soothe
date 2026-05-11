"""TUI progress lines must preserve DisplayLine tree indent."""

from __future__ import annotations

from soothe_cli.cli.stream.pipeline import StreamDisplayPipeline
from soothe_cli.shared.events.essential_events import LOOP_REASON_EVENT_TYPE
from soothe_cli.tui.textual_adapter import _format_progress_event_lines_for_tui


def test_tui_progress_preserves_hierarchy_indent() -> None:
    """Step done aligns with goal-done (flat ● line); subagent rows may still indent.

    IG-225: Assessment/Plan reasoning use level=2 (flat, no indent) for prominence.
    IG-333: Step completion uses level=1 like ``format_goal_done`` (no leading spaces).
    """
    pipeline = StreamDisplayPipeline()

    header = _format_progress_event_lines_for_tui(
        {
            "type": "soothe.cognition.plan.step.started",
            "step_id": "s1",
            "description": "Do the thing",
        },
        (),
        pipeline=pipeline,
    )
    assert header
    assert not header[0].startswith(" ")

    done = _format_progress_event_lines_for_tui(
        {
            "type": "soothe.cognition.plan.step.completed",
            "step_id": "s1",
            "success": True,
            "duration_ms": 1000,
        },
        (),
        pipeline=pipeline,
    )
    assert done
    assert done[0].startswith("● \u2705\ufe0f ")

    # IG-225: Assessment/Plan reasoning now use level=2 (no indent) for prominence
    reason = _format_progress_event_lines_for_tui(
        {
            "type": LOOP_REASON_EVENT_TYPE,
            "next_action": "Continue with analysis",
            "assessment_reasoning": "Progress check",
            "plan_reasoning": "Keep current plan",
            "status": "working",
        },
        (),
        pipeline=pipeline,
    )
    assert len(reason) >= 2
    assert not reason[0].startswith(" ")  # Judgement line (level=2)
    assert not reason[1].startswith(" ")  # Plan line (level=2, IG-225)

    sub_start = _format_progress_event_lines_for_tui(
        {
            "type": "soothe.subagent.research.started",
            "topic_preview": "papers on X",
        },
        (),
        pipeline=pipeline,
    )
    assert sub_start
    assert not sub_start[0].startswith(" ")

    sub_done = _format_progress_event_lines_for_tui(
        {
            "type": "soothe.subagent.research.completed",
            "answer_length": 1200,
            "duration_ms": 1000,
        },
        (),
        pipeline=pipeline,
    )
    assert sub_done
    assert sub_done[0].startswith("  ")
