"""Tests for unified subagent wire display protocol."""

from soothe_sdk.ux.subagent_wire_display import (
    SubagentWireRenderKind,
    classify_subagent_wire_render,
    subagent_wire_row_params,
)


def test_classify_lifecycle_end() -> None:
    assert (
        classify_subagent_wire_render("soothe.subagent.deep_research.completed")
        is SubagentWireRenderKind.LIFECYCLE_END
    )
    assert (
        classify_subagent_wire_render("soothe.subagent.browser_use.failed")
        is SubagentWireRenderKind.LIFECYCLE_END
    )


def test_classify_activity_row() -> None:
    assert (
        classify_subagent_wire_render("soothe.subagent.deep_research.gather.summary")
        is SubagentWireRenderKind.ACTIVITY_ROW
    )
    assert (
        classify_subagent_wire_render("soothe.subagent.browser_use.step.completed")
        is SubagentWireRenderKind.ACTIVITY_ROW
    )


def test_classify_activity_note() -> None:
    assert (
        classify_subagent_wire_render("soothe.subagent.deep_research.progress")
        is SubagentWireRenderKind.ACTIVITY_NOTE
    )
    assert (
        classify_subagent_wire_render("soothe.subagent.veritas.requested")
        is SubagentWireRenderKind.ACTIVITY_NOTE
    )


def test_browser_step_row_params_without_tool_name() -> None:
    params = subagent_wire_row_params(
        "soothe.subagent.browser_use.step.completed",
        {
            "step_index": 2,
            "action_preview": "click submit",
            "url": "https://example.com/form",
            "status": "done",
        },
    )
    assert params is not None
    tool_name, args, phase, _duration = params
    assert tool_name == "BrowserStep"
    assert "click submit" in str(args.get("preview", ""))
    assert phase == "success"
