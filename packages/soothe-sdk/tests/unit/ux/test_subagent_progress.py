"""Tests for subagent wire activity summaries (no per-agent constants in SDK)."""

from soothe_sdk.ux.subagent_progress import summarize_subagent_wire_activity


def test_summarize_explore_step_without_sdk_constants() -> None:
    line = summarize_subagent_wire_activity(
        "soothe.subagent.explore.step.completed",
        {"tool_name": "grep", "args_preview": "pattern=foo"},
    )
    assert "grep" in line
    assert "pattern=foo" in line


def test_summarize_explore_completed_findings() -> None:
    line = summarize_subagent_wire_activity(
        "soothe.subagent.explore.completed",
        {"total_findings": 5, "duration_ms": 2000},
    )
    assert "5 findings" in line
    assert "2000ms" in line


def test_summarize_deep_research_step_completed() -> None:
    line = summarize_subagent_wire_activity(
        "soothe.subagent.deep_research.step.completed",
        {"tool_name": "PlanSearches", "args_preview": "4 queries"},
    )
    assert "PlanSearches" in line
    assert "4 queries" in line


def test_summarize_deep_research_gather_by_suffix() -> None:
    line = summarize_subagent_wire_activity(
        "soothe.subagent.deep_research.gather.summary",
        {"query_preview": "RFC-619", "result_count": 3, "sources_touched": 2},
    )
    assert "RFC-619" in line
    assert "3 hits" in line
