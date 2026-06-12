"""Tests for simple-query planner bypass helpers."""

from __future__ import annotations

from soothe.foundation.loop.planning.simple_bypass import (
    SIMPLE_QUERY_DIRECT_EXPECTED_OUTPUT,
    SIMPLE_QUERY_DIRECT_PREFIX,
    format_simple_query_direct_next_action,
    is_simple_query_direct_next_action,
)


def test_format_simple_query_direct_next_action() -> None:
    text = format_simple_query_direct_next_action("count readmes")
    assert text.startswith(SIMPLE_QUERY_DIRECT_PREFIX)
    assert "count readmes" in text


def test_is_simple_query_direct_next_action_true() -> None:
    assert is_simple_query_direct_next_action(format_simple_query_direct_next_action("hi"))


def test_is_simple_query_direct_next_action_false() -> None:
    assert not is_simple_query_direct_next_action("I'll proceed with analyzing: foo")
    assert not is_simple_query_direct_next_action("")
    assert not is_simple_query_direct_next_action(None)


def test_simple_query_expected_output_requires_result_block() -> None:
    """Bypass expected_output must force a `## Result` block so plan-assess
    sees concrete evidence in the ledger (trace 0e412f regression)."""
    assert "## Result" in SIMPLE_QUERY_DIRECT_EXPECTED_OUTPUT
    assert "MUST" in SIMPLE_QUERY_DIRECT_EXPECTED_OUTPUT
    assert "restate" in SIMPLE_QUERY_DIRECT_EXPECTED_OUTPUT.lower()
