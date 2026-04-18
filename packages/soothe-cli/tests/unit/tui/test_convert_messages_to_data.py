"""Tests for checkpoint message conversion into MessageData."""

from __future__ import annotations

from langchain_core.messages import AIMessage, ToolMessage

from soothe_cli.tui.app import SootheApp
from soothe_cli.tui.widgets.message_store import MessageType, ToolStatus


def test_convert_tool_message_respects_status_error_with_benign_content() -> None:
    messages = [
        AIMessage(
            content="",
            tool_calls=[{"id": "tc1", "name": "read_file", "args": {}}],
        ),
        ToolMessage(
            content="ok",
            tool_call_id="tc1",
            name="read_file",
            status="error",
        ),
    ]
    data = SootheApp._convert_messages_to_data(messages)
    tool_msgs = [m for m in data if m.type == MessageType.TOOL]
    assert len(tool_msgs) == 1
    assert tool_msgs[0].tool_status == ToolStatus.ERROR
    assert tool_msgs[0].tool_output == "ok"


def test_convert_tool_message_list_content_uses_formatted_output() -> None:
    messages = [
        AIMessage(
            content="",
            tool_calls=[{"id": "tc2", "name": "run", "args": {}}],
        ),
        ToolMessage(
            content=["line1", "line2"],
            tool_call_id="tc2",
            name="run",
            status="success",
        ),
    ]
    data = SootheApp._convert_messages_to_data(messages)
    tool_msgs = [m for m in data if m.type == MessageType.TOOL]
    assert len(tool_msgs) == 1
    assert tool_msgs[0].tool_status == ToolStatus.SUCCESS
    assert tool_msgs[0].tool_output == "line1\nline2"
