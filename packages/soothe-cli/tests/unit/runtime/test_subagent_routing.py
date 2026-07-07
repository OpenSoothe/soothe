"""Tests for subagent slash routing."""

from __future__ import annotations

import pytest

from soothe_cli.tui.commands.subagent_routing import (
    get_subagent_display_name,
    parse_subagent_from_input,
)


@pytest.mark.parametrize(
    ("raw", "expected_subagent", "expected_cleaned"),
    [
        ("/deep_research papers", "deep_research", "papers"),
        ("/academic_research transformers", "academic_research", "transformers"),
        ("Please /deep_research find sources", "deep_research", "Please find sources"),
        ("hello", None, "hello"),
    ],
)
def test_parse_subagent_from_input(
    raw: str, expected_subagent: str | None, expected_cleaned: str
) -> None:
    subagent, cleaned = parse_subagent_from_input(raw)
    assert subagent == expected_subagent
    assert cleaned == expected_cleaned


def test_get_subagent_display_name_research_subagents() -> None:
    assert get_subagent_display_name("deep_research") == "Deep Research"
    assert get_subagent_display_name("academic_research") == "Academic Research"
