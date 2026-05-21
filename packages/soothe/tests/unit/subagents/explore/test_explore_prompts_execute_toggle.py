"""Explore system prompt: filesystem-only tools and read-only rules."""

from __future__ import annotations

from soothe.subagents.explore.prompts import format_explore_agent_system


def test_format_explore_agent_system_lists_filesystem_tools_only() -> None:
    body = format_explore_agent_system(
        search_target="foo",
        workspace="/ws",
        thoroughness="quick",
        max_iterations=5,
        max_read_lines=100,
        findings_so_far="",
    )
    assert "glob, grep, ls, read_file, file_info" in body
    assert "run_command" not in body


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
    assert "no shell or write tools" in body


def test_format_explore_agent_system_prefers_native_tool_order() -> None:
    body = format_explore_agent_system(
        search_target="foo",
        workspace="/ws",
        thoroughness="quick",
        max_iterations=5,
        max_read_lines=100,
        findings_so_far="",
    )
    assert "Preferred order" in body
    assert "path discovery" in body
