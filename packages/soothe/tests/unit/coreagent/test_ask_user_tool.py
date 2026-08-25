"""Unit tests for the host-injected ``ask_user`` tool (RFC-622 relay)."""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

import pytest

from soothe.coreagent.tools.ask_user import (
    _AskUserArgs,
    _format_answers,
    build_ask_user_tool,
)

# ---------------------------------------------------------------------------
# Tool construction
# ---------------------------------------------------------------------------


def test_tool_name_and_schema() -> None:
    tool = build_ask_user_tool()
    assert tool.name == "ask_user"
    schema = tool.args_schema.model_json_schema()
    assert "questions" in schema["properties"]
    # min_length=1 enforced by pydantic
    assert schema["required"] == ["questions"]


def test_args_schema_rejects_empty_questions() -> None:
    with pytest.raises(Exception):  # noqa: PT011
        _AskUserArgs(questions=[])


# ---------------------------------------------------------------------------
# _format_answers — resume payload rendering
# ---------------------------------------------------------------------------


def test_format_answers_dict_answers() -> None:
    out = _format_answers(["Which option?"], {"answers": ["Option C"]})
    assert "Q: Which option?" in out
    assert "A: Option C" in out


def test_format_answers_bare_string() -> None:
    out = _format_answers(["Approve?"], "yes")
    assert "A: yes" in out


def test_format_answers_list() -> None:
    out = _format_answers(["Q1?", "Q2?"], ["a1", "a2"])
    assert "A: a1" in out
    assert "A: a2" in out


def test_format_answers_empty_dismissed() -> None:
    out = _format_answers(["Q?"], None)
    assert "dismissed" in out.lower()


def test_format_answers_pads_missing_answers() -> None:
    out = _format_answers(["Q1?", "Q2?"], {"answers": ["only one"]})
    assert "A: only one" in out
    assert "(no answer)" in out


# ---------------------------------------------------------------------------
# _run_ask_user — interrupt emission + resume
# ---------------------------------------------------------------------------


def test_run_ask_user_emits_interrupt_and_returns_answers() -> None:
    """The tool must call interrupt() with the ask_user payload shape."""
    captured: list[dict[str, Any]] = []

    def fake_interrupt(value: Any) -> Any:
        captured.append(value)
        # Simulate the relay resume payload
        return {"answers": ["Option C"]}

    with patch("langgraph.types.interrupt", fake_interrupt):
        result = _run(["Which design option: A, B, or C?"])

    assert len(captured) == 1
    payload = captured[0]
    assert payload["type"] == "ask_user"
    assert payload["questions"] == ["Which design option: A, B, or C?"]
    assert "A: Option C" in result


def test_run_ask_user_strips_empty_questions() -> None:
    captured: list[dict[str, Any]] = []

    def fake_interrupt(value: Any) -> Any:
        captured.append(value)
        return {"answers": ["go"]}

    with patch("langgraph.types.interrupt", fake_interrupt):
        result = _run(["  ", "real question?", ""])

    # Only the non-empty question survives
    assert captured[0]["questions"] == ["real question?"]
    assert "A: go" in result


def test_run_ask_user_all_empty_returns_error() -> None:
    with patch("langgraph.types.interrupt", side_effect=AssertionError("must not call")):
        result = _run(["", "  "])
    assert "Error" in result


def test_run_ask_user_falls_back_when_no_checkpointer() -> None:
    """When interrupt() raises (no checkpointer), degrade gracefully."""
    with patch("langgraph.types.interrupt", side_effect=RuntimeError("no checkpointer")):
        result = _run(["Approve the plan?"])
    assert "unavailable" in result.lower() or "plain text" in result.lower()


# ---------------------------------------------------------------------------
# async path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_arun_ask_user_matches_sync() -> None:
    captured: list[dict[str, Any]] = []

    def fake_interrupt(value: Any) -> Any:
        captured.append(value)
        return {"answers": ["yes"]}

    with patch("langgraph.types.interrupt", fake_interrupt):
        tool = build_ask_user_tool()
        result = await tool.ainvoke({"questions": ["Approve?"]})

    assert captured[0]["type"] == "ask_user"
    assert "A: yes" in result


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _run(questions: list[str]) -> str:
    """Invoke the sync tool handler (bypass StructuredTool dispatch)."""
    from soothe.coreagent.tools.ask_user import _run_ask_user

    return _run_ask_user(questions)
