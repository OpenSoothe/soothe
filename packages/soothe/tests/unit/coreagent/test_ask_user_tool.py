"""Unit tests for the host-injected ``ask_user`` tool (RFC-622 §9c relay)."""

from __future__ import annotations

import json
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


def _opt(label: str = "Option", description: str = "A description.") -> OptionSpec:
    return OptionSpec(label=label, description=description)


def _question(
    question: str = "How should the API authenticate requests?",
    header: str = "Auth",
    options: list[OptionSpec] | None = None,
) -> QuestionSpec:
    return QuestionSpec(
        question=question,
        header=header,
        options=options or [_opt("OAuth"), _opt("API key"), _opt("Session")],
    )


# ---------------------------------------------------------------------------
# Tool construction
# ---------------------------------------------------------------------------


def test_tool_name_and_schema() -> None:
    tool = build_ask_user_tool()
    assert tool.name == "ask_user"
    schema = tool.args_schema.model_json_schema()
    assert "questions" in schema["properties"]


def test_tool_description_mentions_options() -> None:
    tool = build_ask_user_tool()
    assert "options" in tool.description.lower()


# ---------------------------------------------------------------------------
# OptionSpec validation
# ---------------------------------------------------------------------------


def test_option_spec_valid() -> None:
    opt = _opt("OAuth 2.0", "Best for browser flows.")
    assert opt.label == "OAuth 2.0"
    assert opt.description == "Best for browser flows."


def test_option_spec_rejects_empty_label() -> None:
    """Empty option label is rejected by QuestionSpec validation."""
    with pytest.raises(Exception, match="non-empty"):  # noqa: PT011
        _question(options=[_opt("  ", "desc"), _opt("B"), _opt("C")])


def test_option_spec_rejects_empty_description() -> None:
    """Empty option description is rejected by QuestionSpec validation."""
    with pytest.raises(Exception, match="non-empty"):  # noqa: PT011
        _question(options=[_opt("label", "  "), _opt("B"), _opt("C")])


# ---------------------------------------------------------------------------
# QuestionSpec validation
# ---------------------------------------------------------------------------


def test_question_spec_valid() -> None:
    q = _question()
    assert q.header == "Auth"
    assert len(q.options) == 3


def test_question_spec_accepts_2_options() -> None:
    q = _question(options=[_opt("A"), _opt("B")])
    assert len(q.options) == 2


def test_question_spec_accepts_4_options() -> None:
    q = _question(options=[_opt("A"), _opt("B"), _opt("C"), _opt("D")])
    assert len(q.options) == 4


def test_question_spec_rejects_1_option() -> None:
    with pytest.raises(Exception, match="2-4 options"):  # noqa: PT011
        _question(options=[_opt("A")])


def test_question_spec_rejects_5_options() -> None:
    with pytest.raises(Exception, match="2-4 options"):  # noqa: PT011
        _question(options=[_opt("A"), _opt("B"), _opt("C"), _opt("D"), _opt("E")])


def test_question_spec_rejects_header_over_12_chars() -> None:
    with pytest.raises(Exception, match="≤12 chars"):  # noqa: PT011
        _question(header="This header is way too long")


def test_question_spec_rejects_question_over_100_words() -> None:
    long_q = " ".join(["word"] * 101)
    with pytest.raises(Exception, match="≤100 words"):  # noqa: PT011
        _question(question=long_q)


def test_question_spec_rejects_duplicate_option_labels() -> None:
    with pytest.raises(Exception, match="unique"):  # noqa: PT011
        _question(options=[_opt("Same"), _opt("Same"), _opt("C")])


# ---------------------------------------------------------------------------
# _AskUserArgs normalization
# ---------------------------------------------------------------------------


def test_args_schema_rejects_empty() -> None:
    with pytest.raises(Exception):  # noqa: PT011
        _AskUserArgs()


def test_args_schema_rejects_whitespace_only_question() -> None:
    q = _question(question="  ")
    with pytest.raises(Exception, match="non-empty"):  # noqa: PT011
        _AskUserArgs(questions=[q])


def test_args_schema_strips_whitespace_entries() -> None:
    blank = _question(question="  ")
    real = _question(question="Real question?")
    args = _AskUserArgs(questions=[blank, real])
    assert len(args.questions) == 1
    assert args.questions[0].question == "Real question?"


def test_args_schema_accepts_multiple_questions() -> None:
    q1 = _question(question="Q1?", header="H1")
    q2 = _question(question="Q2?", header="H2")
    args = _AskUserArgs(questions=[q1, q2])
    assert len(args.questions) == 2


def test_args_schema_rejects_duplicate_question_texts() -> None:
    q1 = _question(question="Same question?", header="H1")
    q2 = _question(question="Same question?", header="H2")
    with pytest.raises(Exception, match="unique"):  # noqa: PT011
        _AskUserArgs(questions=[q1, q2])


# ---------------------------------------------------------------------------
# LLM arg-quirk coercion (loops f182, 065e, 9125)
# ---------------------------------------------------------------------------


def test_args_schema_coerces_stringified_json_questions() -> None:
    """Loop f182: questions as stringified JSON array."""
    raw = json.dumps(
        [
            {
                "question": "What would you like to discuss first?",
                "header": "Topic",
                "options": [
                    {"label": "A", "description": "Option A desc."},
                    {"label": "B", "description": "Option B desc."},
                    {"label": "C", "description": "Option C desc."},
                ],
            },
        ]
    )
    args = _AskUserArgs(questions=raw)  # type: ignore[arg-type]
    assert len(args.questions) == 1
    assert args.questions[0].question == "What would you like to discuss first?"


def test_args_schema_coerces_stringified_json_via_ainvoke() -> None:
    """The structured tool accepts stringified JSON questions from LLMs."""
    raw = json.dumps([_question().model_dump()])
    tool = build_ask_user_tool()
    captured: list[dict[str, Any]] = []

    def fake_interrupt(value: Any) -> Any:
        captured.append(value)
        return {"answers": ["yes"]}

    with patch("langgraph.types.interrupt", fake_interrupt):
        result = tool.invoke({"questions": raw})

    assert captured[0]["questions"][0]["question"] == "How should the API authenticate requests?"
    assert "A: yes" in result


def test_args_schema_wraps_flat_single_question() -> None:
    """Loop 065e: model emitted question fields as top-level tool args."""
    args = _AskUserArgs(
        question="Project feedback?",
        header="Feedback",
        options=[
            {"label": "A", "description": "Option A desc."},
            {"label": "B", "description": "Option B desc."},
            {"label": "C", "description": "Option C desc."},
        ],
    )  # type: ignore[call-arg]
    assert len(args.questions) == 1
    assert args.questions[0].question == "Project feedback?"


def test_args_schema_coerces_stringified_options() -> None:
    """Loop 065e: options arrived as a JSON string."""
    opts_json = json.dumps(
        [
            {"label": "A", "description": "la"},
            {"label": "B", "description": "lb"},
            {"label": "C", "description": "lc"},
        ]
    )
    args = _AskUserArgs(
        questions=[{"question": "Q?", "header": "H", "options": opts_json}],
    )
    assert len(args.questions[0].options) == 3
    assert args.questions[0].options[0].label == "A"


def test_args_schema_renames_old_field_names() -> None:
    """In-flight loops with old field names (title/short/long) are coerced."""
    args = _AskUserArgs(
        questions=[
            {
                "title": "Auth",
                "description": "Which method?",
                "options": [
                    {"short": "A", "long": "la"},
                    {"short": "B", "long": "lb"},
                    {"short": "C", "long": "lc"},
                ],
                "recommended": 0,
            }
        ],
    )
    assert len(args.questions) == 1
    assert args.questions[0].header == "Auth"
    assert args.questions[0].question == "Which method?"
    assert args.questions[0].options[0].label == "A"
    assert args.questions[0].options[0].description == "la"


# ---------------------------------------------------------------------------
# _format_answers — resume payload rendering
# ---------------------------------------------------------------------------


def test_format_answers_with_question_spec() -> None:
    q = _question(question="Which option?")
    out = _format_answers([q], {"answers": ["OAuth 2.0"]})
    assert "Q: Which option?" in out
    assert "A: OAuth 2.0" in out


def test_format_answers_with_plain_string_fallback() -> None:
    """Plain strings still work for degraded backward compat."""
    out = _format_answers(["Which option?"], {"answers": ["Option C"]})
    assert "Q: Which option?" in out
    assert "A: Option C" in out


def test_format_answers_dict_answers() -> None:
    q = _question(question="Pick one?")
    out = _format_answers([q], {"answers": ["Option C"]})
    assert "A: Option C" in out


def test_format_answers_bare_string() -> None:
    q = _question(question="Approve?")
    out = _format_answers([q], "yes")
    assert "A: yes" in out


def test_format_answers_list() -> None:
    q1 = _question(question="Q1?")
    q2 = _question(question="Q2?")
    out = _format_answers([q1, q2], ["a1", "a2"])
    assert "A: a1" in out
    assert "A: a2" in out


def test_format_answers_empty_dismissed() -> None:
    q = _question(question="Q?")
    out = _format_answers([q], None)
    assert "dismissed" in out.lower()


def test_format_answers_pads_missing_answers() -> None:
    q1 = _question(question="Q1?")
    q2 = _question(question="Q2?")
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
        result = _run(questions=[_question(question="Which option?")])

    assert len(captured) == 1
    payload = captured[0]
    assert payload["type"] == "ask_user"
    assert payload["questions"][0]["question"] == "Which option?"
    assert payload["questions"][0]["options"][0]["label"] == "OAuth"
    assert "A: OAuth 2.0" in result


def test_run_ask_user_serializes_question_spec_dicts() -> None:
    """The interrupt payload must contain model_dump() dicts, not objects."""
    captured: list[dict[str, Any]] = []

    def fake_interrupt(value: Any) -> Any:
        captured.append(value)
        return {"answers": ["yes"]}

    with patch("langgraph.types.interrupt", fake_interrupt):
        _run(questions=[_question(question="Confirm?")])

    payload = captured[0]
    q = payload["questions"][0]
    assert isinstance(q, dict)
    assert "question" in q
    assert "header" in q
    assert "options" in q


def test_run_ask_user_strips_empty_questions() -> None:
    captured: list[dict[str, Any]] = []

    def fake_interrupt(value: Any) -> Any:
        captured.append(value)
        return {"answers": ["go"]}

    with patch("langgraph.types.interrupt", fake_interrupt):
        result = _run(questions=[_question(question="  "), _question(question="real?")])

    assert len(captured[0]["questions"]) == 1
    assert captured[0]["questions"][0]["question"] == "real?"
    assert "A: go" in result


def test_run_ask_user_all_empty_raises_value_error() -> None:
    with patch("langgraph.types.interrupt", side_effect=AssertionError("must not call")):
        with pytest.raises(ValueError, match="non-empty"):
            _run(questions=[_question(question="  ")])


def test_run_ask_user_propagates_graph_interrupt() -> None:
    """GraphInterrupt must propagate — it's the normal pause mechanism."""
    from langgraph.errors import GraphInterrupt
    from langgraph.types import Interrupt

    q = _question(question="Approve?")
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
        result = await tool.ainvoke({"questions": [_question(question="Confirm?").model_dump()]})

    assert captured[0]["type"] == "ask_user"
    assert "A: yes" in result


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _run(*, questions: list[QuestionSpec] | None = None) -> str:
    """Invoke the sync tool handler (bypass StructuredTool dispatch)."""
    from soothe.coreagent.tools.ask_user import _run_ask_user

    return _run_ask_user(questions)
