"""Tests for subagent slash-prefix parsing and routing command wiring."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from soothe_cli.shared.commands.command_router import handle_routing_command
from soothe_cli.shared.commands.subagent_routing import parse_subagent_from_input


@pytest.mark.parametrize(
    ("raw", "expected_subagent", "expected_text"),
    [
        ("/browser open x", "browser", "open x"),
        ("/claude reason", "claude", "reason"),
        ("/research papers", "research", "papers"),
        ("/explore find files", "explore", "find files"),
        ("Please /explore search code", "explore", "Please search code"),
        ("Please /research find sources", "research", "Please find sources"),
        ("/plan do thing", None, "/plan do thing"),
        ("no prefix", None, "no prefix"),
    ],
)
def test_parse_subagent_from_input(
    raw: str, expected_subagent: str | None, expected_text: str
) -> None:
    """Built-in /browser, /claude, /research set subagent; other text is unchanged."""
    subagent, cleaned = parse_subagent_from_input(raw)
    assert subagent == expected_subagent
    assert cleaned == expected_text


@pytest.mark.asyncio
async def test_handle_routing_command_sets_subagent_for_browser() -> None:
    """Routing handler must send cleaned text and WebSocket subagent field."""
    client = MagicMock()
    client.send_input = AsyncMock()
    console = MagicMock()

    await handle_routing_command(
        "/browser open example.com", console, client, loop_id="loop-a"
    )

    client.send_input.assert_awaited_once_with(
        "loop-a", "open example.com", preferred_subagent="browser"
    )


@pytest.mark.asyncio
async def test_handle_routing_command_sets_subagent_for_explore() -> None:
    """Routing handler must send cleaned text and WebSocket subagent field for explore."""
    client = MagicMock()
    client.send_input = AsyncMock()
    console = MagicMock()

    await handle_routing_command(
        "/explore find Python files", console, client, loop_id="loop-a"
    )

    client.send_input.assert_awaited_once_with(
        "loop-a", "find Python files", preferred_subagent="explore"
    )


@pytest.mark.asyncio
async def test_handle_routing_command_plan_untagged() -> None:
    """Non-subagent routing commands pass through without subagent."""
    client = MagicMock()
    client.send_input = AsyncMock()
    console = MagicMock()

    await handle_routing_command(
        "/plan refactor the module", console, client, loop_id="loop-a"
    )

    client.send_input.assert_awaited_once_with(
        "loop-a", "/plan refactor the module", preferred_subagent=None
    )
