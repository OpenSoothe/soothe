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
        ("/browser_use open example.com", "browser_use", "open example.com"),
        ("Please /deep_research find sources", "deep_research", "Please find sources"),
        ("Please /browser_use click login", "browser_use", "Please click login"),
        ("/browser alone", None, "/browser alone"),
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
    assert get_subagent_display_name("browser_use") == "Browser"


def test_slash_registries_include_browser_use() -> None:
    from soothe_cli.tui.command_registry import COMMANDS as UI_COMMANDS
    from soothe_cli.tui.command_registry import SLASH_COMMANDS
    from soothe_cli.tui.commands.slash_commands import COMMANDS as RFC_COMMANDS
    from soothe_cli.tui.commands.subagent_routing import SUBAGENT_SLASH_ROUTE_IDS

    assert "browser_use" in SUBAGENT_SLASH_ROUTE_IDS
    assert any(cmd.name == "/browser_use" for cmd in UI_COMMANDS)
    assert any(name == "/browser_use" for name, _desc, _kw in SLASH_COMMANDS)
    entry = RFC_COMMANDS.get("/browser_use")
    assert entry is not None
    assert entry.get("location") == "daemon"
    assert entry.get("type") == "routing"
    assert entry.get("requires_query") is True
