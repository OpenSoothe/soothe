"""Tests for explore Task JSON display formatting (IG-311)."""

from __future__ import annotations

from soothe_cli.runtime.presentation.explore_task_display import (
    format_explore_task_json_blob_for_display,
)


def test_formats_explore_result_summary() -> None:
    raw = (
        '{"target": "t", "thoroughness": "low", "matches": [], "summary": "Found 3 README files."}'
    )
    assert format_explore_task_json_blob_for_display(raw) == "Found 3 README files."


def test_prefers_summary_over_prior_decisions() -> None:
    raw = (
        '{"decision": "adjust"}'
        '{"decision": "continue"}'
        '{"target": "t", "matches": [], "summary": "Done searching.", "thoroughness": "low"}'
    )
    assert format_explore_task_json_blob_for_display(raw) == "Done searching."


def test_decision_only_chain_suppressed() -> None:
    raw = '{"decision": "adjust"}{"decision": "continue"}'
    assert format_explore_task_json_blob_for_display(raw) == ""


def test_non_json_passthrough() -> None:
    assert format_explore_task_json_blob_for_display("plain prose") == "plain prose"
