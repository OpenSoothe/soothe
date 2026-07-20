"""Tests for progressive tool budget formatter."""

from __future__ import annotations

from soothe_nano.toolkits.progressive.budget import (
    AVAILABLE_TOOLS_PREAMBLE,
    _normalize_tool_summary,
    format_tools_within_budget,
)
from soothe_nano.toolkits.progressive.registry import ToolDescriptor


def test_normalize_strips_usage_section() -> None:
    raw = (
        "Apply a unified diff patch to a file.\n\n"
        "Usage:\n"
        "- Diff must be in standard unified diff format\n"
        "- Uses the 'patch' command"
    )
    assert _normalize_tool_summary(raw) == "Apply a unified diff patch to a file."


def test_normalize_first_sentence_only() -> None:
    raw = (
        "A portal to the internet. Use this when you need to get specific "
        "content from a website. Input should be a url."
    )
    assert _normalize_tool_summary(raw) == "A portal to the internet."


def test_format_aligned_one_line_per_tool() -> None:
    entries = [
        ToolDescriptor(name="add_finding", description="Record a finding for context projection."),
        ToolDescriptor(
            name="wizsearch_search",
            description="Search the web using multiple engines (tavily, duckduckgo).",
        ),
    ]
    text, telemetry = format_tools_within_budget(
        entries, budget_chars=10_000, include_preamble=True
    )
    assert AVAILABLE_TOOLS_PREAMBLE in text
    assert "add_finding" in text
    assert "wizsearch_search" in text
    assert "Usage:" not in text
    assert "Record a finding" in text
    assert telemetry["mode"] == "full"
    # Aligned columns: name padded, double-space before summary
    assert "  add_finding" in text
    assert "  wizsearch_search" in text


def test_format_tools_within_budget_truncates_on_word_boundary() -> None:
    entries = [ToolDescriptor(name=f"tool_{i}", description="x" * 80) for i in range(10)]
    text, telemetry = format_tools_within_budget(
        entries,
        budget_chars=200,
        include_preamble=False,
    )
    assert text
    assert telemetry["mode"] in {"truncated", "names_only", "full"}
    assert telemetry["included_count"] <= len(entries)
    assert "…" not in text or telemetry["mode"] == "truncated"


def test_names_only_mode_when_budget_tight() -> None:
    entries = [
        ToolDescriptor(name="inspect_data", description="Inspect data file structure."),
        ToolDescriptor(name="summarize_data", description="Get statistical summary of data."),
    ]
    text, telemetry = format_tools_within_budget(
        entries,
        budget_chars=25,
        per_entry_cap_chars=10,
        min_per_entry_chars=20,
        include_preamble=False,
    )
    assert telemetry["mode"] == "names_only"
    assert "inspect_data" in text
    assert "summarize_data" in text
    assert "Inspect data" not in text
