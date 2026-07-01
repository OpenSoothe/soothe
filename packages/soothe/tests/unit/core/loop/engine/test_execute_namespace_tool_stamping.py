"""Tests for unified tool_call_id rewriting on ToolMessages (IG-514)."""

from __future__ import annotations

from langchain_core.messages import ToolMessage
from soothe.foundation.sloop.engine.tool_call_id import _rewrite_tool_message_tool_call_id


def test_rewrite_tool_message_in_execute_namespace_uses_step_level_id() -> None:
    """Sole-child thread reuse streams ToolMessages under execute:{run}/N — still step-level."""
    msg = ToolMessage(content="ok", tool_call_id="tool-abc123", name="glob")
    rewritten = _rewrite_tool_message_tool_call_id(msg, "NKX-02", task_idx=None)
    assert rewritten.tool_call_id == "NKX_02:s:tool-abc123"


def test_rewrite_tool_message_in_tools_namespace_uses_task_level_id() -> None:
    msg = ToolMessage(content="ok", tool_call_id="glob:0", name="glob")
    rewritten = _rewrite_tool_message_tool_call_id(msg, "NKX-02", task_idx=0)
    assert rewritten.tool_call_id == "NKX_02:t0:glob:0"
