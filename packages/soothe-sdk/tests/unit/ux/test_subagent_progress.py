"""Tests for subagent wire activity summaries (no per-agent constants in SDK)."""

from soothe_sdk.ux.subagent_progress import summarize_subagent_wire_activity


def test_summarize_browser_step_without_sdk_constants() -> None:
    line = summarize_subagent_wire_activity(
        "soothe.subagent.browser.step.completed",
        {"status": "ok", "action_preview": "click", "url": "https://example.com"},
    )
    assert "ok" in line
    assert "click" in line


def test_summarize_claude_completed_cost() -> None:
    line = summarize_subagent_wire_activity(
        "soothe.subagent.claude.completed",
        {"cost_usd": 1.5, "duration_ms": 2000},
    )
    assert "$1.50" in line
    assert "2000ms" in line


def test_summarize_tacitus_gather_by_suffix() -> None:
    line = summarize_subagent_wire_activity(
        "soothe.subagent.tacitus.gather.summary",
        {"query_preview": "RFC-619", "result_count": 3, "sources_touched": 2},
    )
    assert "RFC-619" in line
    assert "3 hits" in line
