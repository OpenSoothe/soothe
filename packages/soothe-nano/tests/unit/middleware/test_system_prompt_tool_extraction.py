"""Tests for `SystemPromptMiddleware._extract_recent_tool_calls`.

Regression coverage for the trace fe0d optimization: the extractor now
inspects both ``ToolMessage.name`` and ``AIMessage.tool_calls[*].name`` so
loop-continuation bootstrap (which preserves AI envelopes but strips tool
results) still surfaces prior tool usage to the trigger registry.
"""

from __future__ import annotations

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from soothe_nano.config.settings import SootheConfig
from soothe_nano.middleware import SystemPromptMiddleware
from soothe_nano.middleware.system_prompt import (
    RECENT_TOOL_MESSAGE_WINDOW,
    RECENT_TOOL_NAME_CAP,
)


def _mw() -> SystemPromptMiddleware:
    return SystemPromptMiddleware(config=SootheConfig())


def _ai_with_calls(names: list[str]) -> AIMessage:
    return AIMessage(
        content="",
        tool_calls=[{"name": n, "args": {}, "id": f"call_{i}"} for i, n in enumerate(names)],
    )


def test_empty_returns_empty() -> None:
    assert _mw()._extract_recent_tool_calls([]) == []


def test_tool_messages_only_most_recent_first() -> None:
    msgs = [
        ToolMessage(content="ok", tool_call_id="a", name="glob"),
        ToolMessage(content="ok", tool_call_id="b", name="run_python"),
    ]
    assert _mw()._extract_recent_tool_calls(msgs) == ["run_python", "glob"]


def test_ai_message_tool_calls_only() -> None:
    """Regression: bootstrap inject preserves AIMessage but no ToolMessage."""
    msgs = [
        HumanMessage(content="goal"),
        _ai_with_calls(["glob", "run_python"]),
    ]
    result = _mw()._extract_recent_tool_calls(msgs)
    # AIMessage.tool_calls preserves invocation order; reversed walk hits
    # this AIMessage first, then iterates its tool_calls in their own order.
    assert result == ["glob", "run_python"]


def test_mixed_dedup_preserves_most_recent_first() -> None:
    msgs = [
        _ai_with_calls(["glob"]),
        ToolMessage(content="ok", tool_call_id="a", name="glob"),
        _ai_with_calls(["run_python"]),
        ToolMessage(content="ok", tool_call_id="b", name="run_python"),
    ]
    result = _mw()._extract_recent_tool_calls(msgs)
    assert result == ["run_python", "glob"]


def test_window_cap_only_scans_latest_messages() -> None:
    older = [ToolMessage(content="ok", tool_call_id=f"x{i}", name="old_tool") for i in range(5)]
    newer = [
        ToolMessage(content="ok", tool_call_id=f"y{i}", name="new_tool")
        for i in range(RECENT_TOOL_MESSAGE_WINDOW)
    ]
    msgs: list = [*older, *newer]
    result = _mw()._extract_recent_tool_calls(msgs)
    assert result == ["new_tool"]
    assert "old_tool" not in result


def test_name_cap_honored() -> None:
    distinct = [
        ToolMessage(content="ok", tool_call_id=f"c{i}", name=f"tool_{i}")
        for i in range(RECENT_TOOL_NAME_CAP + 5)
    ]
    result = _mw()._extract_recent_tool_calls(distinct)
    assert len(result) == RECENT_TOOL_NAME_CAP


def test_unnamed_tool_calls_are_skipped() -> None:
    msgs = [
        ToolMessage(content="ok", tool_call_id="a", name=""),
        ToolMessage(content="ok", tool_call_id="b", name="glob"),
    ]
    assert _mw()._extract_recent_tool_calls(msgs) == ["glob"]
