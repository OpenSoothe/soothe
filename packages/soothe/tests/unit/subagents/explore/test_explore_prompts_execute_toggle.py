"""Explore system prompt includes run_command shell tool."""

from __future__ import annotations

from soothe.subagents.explore.prompts import format_explore_agent_system


def test_format_explore_agent_system_includes_run_command() -> None:
    body = format_explore_agent_system(
        search_target="foo",
        workspace="/ws",
        thoroughness="quick",
        max_iterations=5,
        max_read_lines=100,
        findings_so_far="",
    )
    assert "run_command (shell)" in body
    assert "`run_command`" in body


def test_format_explore_agent_system_includes_read_only_rules() -> None:
    body = format_explore_agent_system(
        search_target="foo",
        workspace="/ws",
        thoroughness="quick",
        max_iterations=5,
        max_read_lines=100,
        findings_so_far="",
    )
    assert "read-only" in body
    assert "Forbidden command classes" in body
