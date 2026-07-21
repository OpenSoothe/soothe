"""Tests for subagent wire activity summaries (no per-agent constants in SDK)."""

from soothe_sdk.ux.subagent_progress import summarize_subagent_wire_activity


def test_summarize_generic_subagent_step_without_sdk_constants() -> None:
    line = summarize_subagent_wire_activity(
        "soothe.subagent.browser_use.step.completed",
        {"tool_name": "grep", "args_preview": "pattern=foo"},
    )
    assert "grep" in line
    assert "pattern=foo" in line


def test_summarize_generic_subagent_completed_findings() -> None:
    line = summarize_subagent_wire_activity(
        "soothe.subagent.browser_use.completed",
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


def test_summarize_deep_research_progress() -> None:
    line = summarize_subagent_wire_activity(
        "soothe.subagent.deep_research.progress",
        {"phase": "gather", "message": "Searching web", "loop_count": 1, "total_loops": 3},
    )
    assert "gather" in line
    assert "Searching web" in line
    assert "1/3" in line


def test_summarize_deep_research_crawl_summary() -> None:
    line = summarize_subagent_wire_activity(
        "soothe.subagent.deep_research.crawl.summary",
        {"urls_crawled": 5, "success_count": 4},
    )
    assert "4/5 URLs crawled" in line


def test_summarize_deep_research_completed_includes_saved_path() -> None:
    line = summarize_subagent_wire_activity(
        "soothe.subagent.deep_research.completed",
        {
            "summary": "Widgets are growing fast.",
            "report_path": ".soothe/agents/deep_research/key-findings_20260709.md",
            "duration_ms": 1200,
        },
    )
    assert "Widgets are growing fast." in line
    assert ".soothe/agents/deep_research/key-findings_20260709.md" in line
    assert "1200ms" in line


def test_summarize_veritas_requested() -> None:
    line = summarize_subagent_wire_activity(
        "soothe.subagent.veritas.requested",
        {"question_count": 2},
    )
    assert "Veritas clarifying" in line
    assert "2 questions" in line


def test_summarize_veritas_answered() -> None:
    line = summarize_subagent_wire_activity(
        "soothe.subagent.veritas.answered",
        {"confidence": 0.85, "defer": False},
    )
    assert "Veritas answered" in line
    assert "0.85" in line
