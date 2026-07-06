"""Tests for invalid-tool hint helpers and middleware."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from langchain_core.messages import ToolMessage
from langgraph.types import Command

from soothe.middleware.invalid_tool_hints import InvalidToolHintsMiddleware
from soothe.middleware.tool_name_hints import (
    append_hint_to_tool_result,
    is_invalid_tool_error,
    sanitize_hallucinated_tool_name,
    suggest_invalid_tool_hint,
)


def test_is_invalid_tool_error() -> None:
    assert is_invalid_tool_error("Error: read_command is not a valid tool, try one of [ls].")
    assert not is_invalid_tool_error("Error: File not found")


def test_suggest_hint_for_read_command_with_command_arg() -> None:
    hint = suggest_invalid_tool_hint(
        "read_command",
        {"command": "grep -n foo bar.go"},
    )
    assert hint is not None
    assert "run_command" in hint


def test_suggest_hint_for_path_embedded_in_ls_name() -> None:
    hint = suggest_invalid_tool_hint(
        "ls /tmp/foo</arg_value>",
        {},
    )
    assert hint is not None
    assert "ls" in hint
    assert "/tmp/foo" in hint


def test_sanitize_embedded_path_in_tool_name() -> None:
    name, args = sanitize_hallucinated_tool_name("read_file /tmp/a.go</arg_value>")
    assert name == "read_file"
    assert args == {"file_path": "/tmp/a.go"}


def test_append_hint_to_tool_message() -> None:
    msg = ToolMessage(
        content="Error: read_command is not a valid tool, try one of [run_command].",
        tool_call_id="t1",
        name="read_command",
        status="error",
    )
    updated = append_hint_to_tool_result(msg, hint="Hint: use run_command.")
    assert isinstance(updated, ToolMessage)
    assert "Hint: use run_command." in str(updated.content)


@pytest.mark.asyncio
async def test_invalid_tool_hints_middleware_appends_hint() -> None:
    middleware = InvalidToolHintsMiddleware()
    request = MagicMock()
    request.tool_call = {
        "name": "read_command",
        "args": {"command": "ls"},
        "id": "c1",
    }

    async def handler(_req: object) -> ToolMessage:
        return ToolMessage(
            content="Error: read_command is not a valid tool, try one of [run_command].",
            tool_call_id="c1",
            name="read_command",
            status="error",
        )

    result = await middleware.awrap_tool_call(request, handler)
    assert isinstance(result, ToolMessage)
    assert "run_command" in str(result.content)
    assert "Hint:" in str(result.content)


@pytest.mark.asyncio
async def test_invalid_tool_hints_middleware_passes_through_success() -> None:
    middleware = InvalidToolHintsMiddleware()
    request = MagicMock()
    request.tool_call = {"name": "run_command", "args": {"command": "true"}, "id": "c2"}

    async def handler(_req: object) -> ToolMessage:
        return ToolMessage(content="ok", tool_call_id="c2", name="run_command")

    result = await middleware.awrap_tool_call(request, handler)
    assert isinstance(result, ToolMessage)
    assert result.content == "ok"


@pytest.mark.asyncio
async def test_invalid_tool_hints_middleware_enhances_command_wrapper() -> None:
    middleware = InvalidToolHintsMiddleware()
    request = MagicMock()
    request.tool_call = {
        "name": "ls /tmp</arg_value>",
        "args": {},
        "id": "c3",
    }

    async def handler(_req: object) -> Command:
        return Command(
            update={
                "messages": [
                    ToolMessage(
                        content="Error: ls /tmp</arg_value> is not a valid tool, try one of [ls].",
                        tool_call_id="c3",
                        name="ls /tmp</arg_value>",
                        status="error",
                    )
                ]
            }
        )

    result = await middleware.awrap_tool_call(request, handler)
    assert isinstance(result, Command)
    update = result.update
    assert isinstance(update, dict)
    msg = update["messages"][0]
    assert isinstance(msg, ToolMessage)
    assert "Hint:" in str(msg.content)
