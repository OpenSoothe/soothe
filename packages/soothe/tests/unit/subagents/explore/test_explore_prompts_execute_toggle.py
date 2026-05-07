"""Explore system prompt reflects whether the shell tool is enabled."""

from __future__ import annotations

from soothe.subagents.explore.prompts import format_explore_agent_system


def test_format_explore_agent_system_omits_execute_when_disabled() -> None:
    body = format_explore_agent_system(
        search_target="foo",
        workspace="/ws",
        thoroughness="quick",
        max_iterations=5,
        max_read_lines=100,
        findings_so_far="",
        include_execute=False,
    )
    assert "execute (shell)" not in body
    assert "not available in this configuration" in body


def test_format_explore_agent_system_includes_execute_when_enabled() -> None:
    body = format_explore_agent_system(
        search_target="foo",
        workspace="/ws",
        thoroughness="quick",
        max_iterations=5,
        max_read_lines=100,
        findings_so_far="",
        include_execute=True,
    )
    assert "execute (shell)" in body
    assert "`execute` (shell)" in body
