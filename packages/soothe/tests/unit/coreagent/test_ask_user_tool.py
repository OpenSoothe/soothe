"""Unit tests for the host-injected ``ask_user`` tool (RFC-622 §9c relay)."""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

import pytest

from soothe.coreagent.tools.ask_user import (
    OptionSpec,
    QuestionSpec,
    _AskUserArgs,
    _format_answers,
    build_ask_user_tool,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _opt(short: str = "Option", long: str = "A description.") -> OptionSpec:
    return OptionSpec(short=short, long=long)


def _question(
    title: str = "Auth method",
    description: str = "How should the API authenticate requests?",
    options: list[OptionSpec] | None = None,
    recommended: int = 0,
) -> QuestionSpec:
    return QuestionSpec(
        title=title,
        description=description,
        options=options or [_opt("OAuth"), _opt("API key"), _opt("Session")],
        recommended=recommended,
    )


# ---------------------------------------------------------------------------
# Tool construction
# ---------------------------------------------------------------------------


def test_tool_name_and_schema() -> None:
    tool = build_ask_user_tool()
    assert tool.name == "ask_user"
    schema = tool.args_schema.model_json_schema()
    assert "questions" in schema["properties"]
    # The singular aliases (question/query) are gone — structured only.
    assert "question" not in schema["properties"]
    assert "query" not in schema["properties"]


def test_tool_description_mentions_structured_options() -> None:
    tool = build_ask_user_tool()
    assert "options" in tool.description.lower()


# ---------------------------------------------------------------------------
# OptionSpec validation
# ---------------------------------------------------------------------------


def test_option_spec_valid() -> None:
    opt = _opt("OAuth 2.0", "Best for browser flows.")
    assert opt.short == "OAuth 2.0"
    assert opt.long == "Best for browser flows."


def test_option_spec_rejects_empty_short() -> None:
    """Empty option short is rejected by QuestionSpec validation."""
    with pytest.raises(Exception, match="non-empty"):  # noqa: PT011
        _question(options=[_opt("  ", "desc"), _opt("B"), _opt("C")])


def test_option_spec_rejects_empty_long() -> None:
    """Empty option long is rejected by QuestionSpec validation."""
    with pytest.raises(Exception, match="non-empty"):  # noqa: PT011
        _question(options=[_opt("short", "  "), _opt("B"), _opt("C")])


def test_option_spec_rejects_short_over_12_words() -> None:
    """Option short >12 words is rejected by QuestionSpec validation."""
    long_short = " ".join(["word"] * 13)
    with pytest.raises(Exception, match="≤12 words"):  # noqa: PT011
        _question(options=[_opt(long_short, "desc"), _opt("B"), _opt("C")])


# ---------------------------------------------------------------------------
# QuestionSpec validation
# ---------------------------------------------------------------------------


def test_question_spec_valid() -> None:
    q = _question()
    assert q.title == "Auth method"
    assert len(q.options) == 3
    assert q.recommended == 0


def test_question_spec_rejects_not_3_options() -> None:
    with pytest.raises(Exception, match="exactly 3"):  # noqa: PT011
        _question(options=[_opt("A"), _opt("B")])

    with pytest.raises(Exception, match="exactly 3"):  # noqa: PT011
        _question(options=[_opt("A"), _opt("B"), _opt("C"), _opt("D")])


def test_question_spec_rejects_recommended_out_of_range() -> None:
    with pytest.raises(Exception, match="recommended"):  # noqa: PT011
        _question(recommended=3)

    with pytest.raises(Exception, match="recommended"):  # noqa: PT011
        _question(recommended=-2)


def test_question_spec_accepts_recommended_minus_one() -> None:
    q = _question(recommended=-1)
    assert q.recommended == -1


def test_question_spec_rejects_title_over_3_words() -> None:
    with pytest.raises(Exception, match="≤3 words"):  # noqa: PT011
        _question(title="This is too many words here")


def test_question_spec_rejects_description_over_100_words() -> None:
    long_desc = " ".join(["word"] * 101)
    with pytest.raises(Exception, match="≤100 words"):  # noqa: PT011
        _question(description=long_desc)


# ---------------------------------------------------------------------------
# _AskUserArgs normalization
# ---------------------------------------------------------------------------


def test_args_schema_rejects_empty() -> None:
    with pytest.raises(Exception):  # noqa: PT011
        _AskUserArgs()


def test_args_schema_rejects_whitespace_only_title() -> None:
    q = _question(title="  ")
    with pytest.raises(Exception, match="non-empty"):  # noqa: PT011
        _AskUserArgs(questions=[q])


def test_args_schema_strips_whitespace_title_entries() -> None:
    blank = _question(title="  ")
    real = _question(title="Real question")
    args = _AskUserArgs(questions=[blank, real])
    assert len(args.questions) == 1
    assert args.questions[0].title == "Real question"


def test_args_schema_accepts_multiple_questions() -> None:
    q1 = _question(title="Q1")
    q2 = _question(title="Q2")
    args = _AskUserArgs(questions=[q1, q2])
    assert len(args.questions) == 2


# ---------------------------------------------------------------------------
# _format_answers — resume payload rendering
# ---------------------------------------------------------------------------


def test_format_answers_with_question_spec_title() -> None:
    q = _question(title="Auth method")
    out = _format_answers([q], {"answers": ["OAuth 2.0"]})
    assert "Q: Auth method" in out
    assert "A: OAuth 2.0" in out


def test_format_answers_with_plain_string_fallback() -> None:
    """Plain strings still work for degraded backward compat."""
    out = _format_answers(["Which option?"], {"answers": ["Option C"]})
    assert "Q: Which option?" in out
    assert "A: Option C" in out


def test_format_answers_dict_answers() -> None:
    q = _question(title="Pick one")
    out = _format_answers([q], {"answers": ["Option C"]})
    assert "A: Option C" in out


def test_format_answers_bare_string() -> None:
    q = _question(title="Approve")
    out = _format_answers([q], "yes")
    assert "A: yes" in out


def test_format_answers_list() -> None:
    q1 = _question(title="Q1")
    q2 = _question(title="Q2")
    out = _format_answers([q1, q2], ["a1", "a2"])
    assert "A: a1" in out
    assert "A: a2" in out


def test_format_answers_empty_dismissed() -> None:
    q = _question(title="Q")
    out = _format_answers([q], None)
    assert "dismissed" in out.lower()


def test_format_answers_pads_missing_answers() -> None:
    q1 = _question(title="Q1")
    q2 = _question(title="Q2")
    out = _format_answers([q1, q2], {"answers": ["only one"]})
    assert "A: only one" in out
    assert "(no answer)" in out


# ---------------------------------------------------------------------------
# _run_ask_user — interrupt emission + resume
# ---------------------------------------------------------------------------


def test_run_ask_user_emits_interrupt_and_returns_answers() -> None:
    """The tool must call interrupt() with the structured ask_user payload."""
    captured: list[dict[str, Any]] = []

    def fake_interrupt(value: Any) -> Any:
        captured.append(value)
        return {"answers": ["OAuth 2.0"]}

    with patch("langgraph.types.interrupt", fake_interrupt):
        result = _run(questions=[_question(title="Auth method")])

    assert len(captured) == 1
    payload = captured[0]
    assert payload["type"] == "ask_user"
    assert payload["questions"][0]["title"] == "Auth method"
    assert payload["questions"][0]["options"][0]["short"] == "OAuth"
    assert "A: OAuth 2.0" in result


def test_run_ask_user_serializes_question_spec_dicts() -> None:
    """The interrupt payload must contain model_dump() dicts, not objects."""
    captured: list[dict[str, Any]] = []

    def fake_interrupt(value: Any) -> Any:
        captured.append(value)
        return {"answers": ["yes"]}

    with patch("langgraph.types.interrupt", fake_interrupt):
        _run(questions=[_question(title="Confirm")])

    payload = captured[0]
    q = payload["questions"][0]
    assert isinstance(q, dict)
    assert "title" in q
    assert "description" in q
    assert "options" in q
    assert "recommended" in q


def test_run_ask_user_strips_empty_title_questions() -> None:
    captured: list[dict[str, Any]] = []

    def fake_interrupt(value: Any) -> Any:
        captured.append(value)
        return {"answers": ["go"]}

    with patch("langgraph.types.interrupt", fake_interrupt):
        result = _run(questions=[_question(title="  "), _question(title="real")])

    assert len(captured[0]["questions"]) == 1
    assert captured[0]["questions"][0]["title"] == "real"
    assert "A: go" in result


def test_run_ask_user_all_empty_raises_value_error() -> None:
    with patch("langgraph.types.interrupt", side_effect=AssertionError("must not call")):
        with pytest.raises(ValueError, match="non-empty"):
            _run(questions=[_question(title="  ")])


def test_run_ask_user_propagates_graph_interrupt() -> None:
    """GraphInterrupt must propagate — it's the normal pause mechanism."""
    from langgraph.errors import GraphInterrupt
    from langgraph.types import Interrupt

    q = _question(title="Approve")
    exc = GraphInterrupt(
        (Interrupt(value={"type": "ask_user", "questions": [q.model_dump()]}, id="i1"),)
    )
    with patch("langgraph.types.interrupt", side_effect=exc):
        with pytest.raises(GraphInterrupt):
            _run(questions=[q])


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
        result = await tool.ainvoke({"questions": [_question(title="Confirm").model_dump()]})

    assert captured[0]["type"] == "ask_user"
    assert "A: yes" in result


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _run(*, questions: list[QuestionSpec] | None = None) -> str:
    """Invoke the sync tool handler (bypass StructuredTool dispatch)."""
    from soothe.coreagent.tools.ask_user import _run_ask_user

    return _run_ask_user(questions)
