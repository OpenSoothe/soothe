"""Tests for unified tool result card payload extraction."""

from __future__ import annotations

from langchain_core.messages import AIMessage, ToolMessage

from soothe_cli.shared.tool_card_payload import extract_tool_result_card_payload


def test_extract_from_tool_message_success() -> None:
    msg = ToolMessage(
        content='{"ok": true}',
        tool_call_id="tc-1",
        name="read_file",
        status="success",
    )
    p = extract_tool_result_card_payload(msg)
    assert p is not None
    assert p.tool_call_id == "tc-1"
    assert p.tool_name == "read_file"
    assert p.is_error is False
    assert "ok" in p.output_display


def test_extract_from_tool_message_error_status() -> None:
    msg = ToolMessage(
        content="failed",
        tool_call_id="tc-2",
        name="run",
        status="error",
    )
    p = extract_tool_result_card_payload(msg)
    assert p is not None
    assert p.is_error is True


def test_extract_from_wire_dict_tool() -> None:
    chunk = {
        "type": "tool",
        "tool_call_id": "tc-3",
        "name": "ls",
        "status": "success",
        "content": '["a", "b"]',
    }
    p = extract_tool_result_card_payload(chunk)
    assert p is not None
    assert p.tool_call_id == "tc-3"
    assert p.tool_name == "ls"
    assert p.is_error is False


def test_extract_from_non_tool_returns_none() -> None:
    assert extract_tool_result_card_payload(AIMessage(content="hi")) is None
    assert extract_tool_result_card_payload({"type": "human"}) is None


def test_extract_infers_tool_name_from_functions_id_when_name_is_placeholder() -> None:
    """Orphan / wire payloads sometimes use name ``tool``; recover from ``functions.*`` id."""
    msg = ToolMessage(
        content="[]",
        tool_call_id="functions.ls:0",
        name="tool",
        status="success",
    )
    p = extract_tool_result_card_payload(msg)
    assert p is not None
    assert p.tool_name == "ls"
