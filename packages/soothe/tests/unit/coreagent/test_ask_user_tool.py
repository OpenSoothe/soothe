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
    assert "question" in schema["properties"]


def test_args_schema_rejects_empty() -> None:
    with pytest.raises(Exception):  # noqa: PT011
        _AskUserArgs()


def test_args_schema_question_alias() -> None:
    """`question` (single string) is accepted as an alias for `questions`."""
    args = _AskUserArgs(question="Which option?")
    assert args.questions == ["Which option?"]


def test_args_schema_query_alias() -> None:
    """`query` is accepted as an alias — models sometimes emit it."""
    args = _AskUserArgs(query="Which option?")
    assert args.questions == ["Which option?"]


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
        return {"answers": ["Option C"]}

    with patch("langgraph.types.interrupt", fake_interrupt):
        result = _run(questions=["Which design option: A, B, or C?"])

    assert len(captured) == 1
    payload = captured[0]
    assert payload["type"] == "ask_user"
    assert payload["questions"] == ["Which design option: A, B, or C?"]
    assert "A: Option C" in result


def test_run_ask_user_with_question_alias() -> None:
    """`question=` (single string) works the same as `questions=[...]`."""
    captured: list[dict[str, Any]] = []

    def fake_interrupt(value: Any) -> Any:
        captured.append(value)
        return {"answers": ["yes"]}

    with patch("langgraph.types.interrupt", fake_interrupt):
        from soothe.coreagent.tools.ask_user import _run_ask_user

        result = _run_ask_user(question="Approve?")

    assert captured[0]["questions"] == ["Approve?"]
    assert "A: yes" in result


def test_run_ask_user_with_query_alias() -> None:
    """`query=` works the same as `question=`."""
    captured: list[dict[str, Any]] = []

    def fake_interrupt(value: Any) -> Any:
        captured.append(value)
        return {"answers": ["yes"]}

    with patch("langgraph.types.interrupt", fake_interrupt):
        from soothe.coreagent.tools.ask_user import _run_ask_user

        result = _run_ask_user(query="Approve?")

    assert captured[0]["questions"] == ["Approve?"]
    assert "A: yes" in result


def test_run_ask_user_strips_empty_questions() -> None:
    captured: list[dict[str, Any]] = []

    def fake_interrupt(value: Any) -> Any:
        captured.append(value)
        return {"answers": ["go"]}

    with patch("langgraph.types.interrupt", fake_interrupt):
        result = _run(questions=["  ", "real question?", ""])

    assert captured[0]["questions"] == ["real question?"]
    assert "A: go" in result


def test_run_ask_user_all_empty_raises_value_error() -> None:
    with patch("langgraph.types.interrupt", side_effect=AssertionError("must not call")):
        with pytest.raises(ValueError, match="non-empty"):
            _run(questions=["", "  "])


def test_args_schema_rejects_whitespace_only() -> None:
    with pytest.raises(Exception, match="non-empty"):  # noqa: PT011
        _AskUserArgs(questions=["  ", "\t", "\n"])


def test_args_schema_strips_whitespace_entries() -> None:
    args = _AskUserArgs(questions=["  ", "real question?"])
    assert args.questions == ["real question?"]


def test_run_ask_user_propagates_graph_interrupt() -> None:
    """GraphInterrupt must propagate — it's the normal pause mechanism."""
    from langgraph.errors import GraphInterrupt
    from langgraph.types import Interrupt

    exc = GraphInterrupt((Interrupt(value={"type": "ask_user", "questions": ["q"]}, id="i1"),))
    with patch("langgraph.types.interrupt", side_effect=exc):
        with pytest.raises(GraphInterrupt):
            _run(questions=["Approve the plan?"])


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


@pytest.mark.asyncio
async def test_arun_ask_user_with_question_field() -> None:
    """The LLM frequently sends {'question': '...'} — verify it works."""
    captured: list[dict[str, Any]] = []

    def fake_interrupt(value: Any) -> Any:
        captured.append(value)
        return {"answers": ["do it"]}

    with patch("langgraph.types.interrupt", fake_interrupt):
        tool = build_ask_user_tool()
        result = await tool.ainvoke({"question": "Should I proceed?"})

    assert captured[0]["questions"] == ["Should I proceed?"]
    assert "A: do it" in result


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _run(*, questions: list[str] | None = None, question: str | None = None) -> str:
    """Invoke the sync tool handler (bypass StructuredTool dispatch)."""
    from soothe.coreagent.tools.ask_user import _run_ask_user

    return _run_ask_user(questions, question=question)
