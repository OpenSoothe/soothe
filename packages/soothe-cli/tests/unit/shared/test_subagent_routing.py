"""Tests for subagent slash-prefix parsing and routing command wiring."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from soothe_cli.shared.command_router import handle_routing_command
from soothe_cli.shared.subagent_routing import parse_subagent_from_input


@pytest.mark.parametrize(
    ("raw", "expected_subagent", "expected_text"),
    [
        ("/browser open x", "browser", "open x"),
        ("/claude reason", "claude", "reason"),
        ("/research papers", "research", "papers"),
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

    await handle_routing_command("/browser open example.com", console, client)

    client.send_input.assert_awaited_once_with("open example.com", subagent="browser")


@pytest.mark.asyncio
async def test_handle_routing_command_plan_untagged() -> None:
    """Non-subagent routing commands pass through without subagent."""
    client = MagicMock()
    client.send_input = AsyncMock()
    console = MagicMock()

    await handle_routing_command("/plan refactor the module", console, client)

    client.send_input.assert_awaited_once_with("/plan refactor the module", subagent=None)
