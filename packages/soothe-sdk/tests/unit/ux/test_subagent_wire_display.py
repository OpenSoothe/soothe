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
        classify_subagent_wire_render("soothe.subagent.academic_research.progress")
        is SubagentWireRenderKind.ACTIVITY_NOTE
    )
    assert (
        classify_subagent_wire_render("soothe.subagent.veritas.requested")
        is SubagentWireRenderKind.ACTIVITY_NOTE
    )


def test_academic_gather_row_uses_academic_search_label() -> None:
    params = subagent_wire_row_params(
        "soothe.subagent.academic_research.gather.summary",
        {"query_preview": "transformer attention", "result_count": 5, "sources_touched": 3},
    )
    assert params is not None
    tool_name, args, phase, _duration = params
    assert tool_name == "AcademicSearch"
    assert "transformer attention" in str(args.get("query", ""))
    assert phase == "success"


def test_browser_step_row_params_without_tool_name() -> None:
    params = subagent_wire_row_params(
        "soothe.subagent.browser_use.step.completed",
        {
            "step_index": 2,
            "action_preview": "click submit",
            "url": "https://example.com/form",
            "title": "Login",
            "status": "done",
            "duration_ms": 350,
        },
    )
    assert params is not None
    tool_name, args, phase, duration_ms = params
    assert tool_name == "BrowserStep#2"
    preview = str(args.get("preview", ""))
    assert "click submit" in preview
    assert phase == "success"
    assert duration_ms == 350


def test_browser_step_row_params_with_humanized_tool_name() -> None:
    params = subagent_wire_row_params(
        "soothe.subagent.browser_use.step.completed",
        {
            "step_index": 3,
            "tool_name": "Navigate",
            "action_preview": "https://www.moji.com/Weather",
            "url": "https://www.moji.com/Weather?city=Zhoushan",
            "title": "moji.com/Weather",
            "status": "done",
            "duration_ms": 13209,
        },
    )
    assert params is not None
    tool_name, args, phase, duration_ms = params
    assert tool_name == "Navigate"
    assert "moji.com" in str(args.get("preview", ""))
    assert phase == "success"
    assert duration_ms == 13209


def test_browser_step_error_status_maps_to_error_phase() -> None:
    params = subagent_wire_row_params(
        "soothe.subagent.browser_use.step.completed",
        {
            "step_index": 1,
            "action_preview": "navigate",
            "url": "https://example.com",
            "status": "error",
        },
    )
    assert params is not None
    _tool_name, _args, phase, _duration = params
    assert phase == "error"
