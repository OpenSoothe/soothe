"""Tests for autonomous slash command parsing."""

from soothe.cli.slash_commands import parse_autonomous_command


def test_parse_autonomous_command_without_limit() -> None:
    assert parse_autonomous_command("/auto Crawl skill pages") == (None, "Crawl skill pages")


def test_parse_autonomous_command_with_limit() -> None:
    assert parse_autonomous_command("/auto 25 Crawl skill pages") == (25, "Crawl skill pages")


def test_parse_autonomous_command_requires_prompt() -> None:
    assert parse_autonomous_command("/auto") is None
    assert parse_autonomous_command("/auto 10") is None


def test_parse_autonomous_command_non_auto() -> None:
    assert parse_autonomous_command("/help") is None


def test_parse_autopilot_alias_without_limit() -> None:
    assert parse_autonomous_command("/autopilot Crawl skill pages") == (None, "Crawl skill pages")


def test_parse_autopilot_alias_with_limit() -> None:
    assert parse_autonomous_command("/autopilot 25 Crawl skill pages") == (25, "Crawl skill pages")


def test_parse_autopilot_alias_requires_prompt() -> None:
    assert parse_autonomous_command("/autopilot") is None
    assert parse_autonomous_command("/autopilot 10") is None
