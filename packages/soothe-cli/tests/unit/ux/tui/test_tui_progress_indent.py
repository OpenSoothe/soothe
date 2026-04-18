"""TUI progress lines must preserve DisplayLine tree indent."""

from __future__ import annotations

from soothe_cli.cli.stream.pipeline import StreamDisplayPipeline
from soothe_cli.shared.essential_events import LOOP_REASON_EVENT_TYPE
from soothe_cli.tui.textual_adapter import _format_progress_event_lines_for_tui


def test_tui_progress_preserves_hierarchy_indent() -> None:
    """Child rows (step done, reasoning, subagent done) keep leading spaces vs parents."""
    pipeline = StreamDisplayPipeline(verbosity="normal")

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
    assert done[0].startswith("  ")

    reason = _format_progress_event_lines_for_tui(
        {
            "type": LOOP_REASON_EVENT_TYPE,
            "next_action": "Continue with analysis",
            "reasoning": "Need more context",
            "status": "working",
        },
        (),
        pipeline=pipeline,
    )
    assert len(reason) >= 2
    assert not reason[0].startswith(" ")
    assert reason[1].startswith("  ")

    sub_start = _format_progress_event_lines_for_tui(
        {
            "type": "soothe.capability.research.started",
            "query": "papers on X",
        },
        (),
        pipeline=pipeline,
    )
    assert sub_start
    assert not sub_start[0].startswith(" ")

    sub_done = _format_progress_event_lines_for_tui(
        {
            "type": "soothe.capability.research.completed",
            "summary": "5 papers",
            "duration_s": 1.0,
        },
        (),
        pipeline=pipeline,
    )
    assert sub_done
    assert sub_done[0].startswith("  ")
