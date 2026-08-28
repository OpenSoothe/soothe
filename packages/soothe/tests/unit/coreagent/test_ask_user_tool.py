"""Unit tests for the host-injected ``ask_user`` tool."""

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


def test_option_spec_coerces_empty_label() -> None:
    """Empty option label is coerced to a placeholder by QuestionSpec."""
    q = _question(options=[_opt("  ", "desc"), _opt("B"), _opt("C")])
    assert q.options[0].label == "Option 1"


def test_option_spec_coerces_empty_description() -> None:
    """Empty option description is coerced to a placeholder by QuestionSpec."""
    q = _question(options=[_opt("label", "  "), _opt("B"), _opt("C")])
    assert q.options[0].description == "No description provided."


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


def test_question_spec_pads_1_option() -> None:
    """Fewer than 2 options is padded to 2 by coercion."""
    q = _question(options=[_opt("A")])
    assert len(q.options) == 2


def test_question_spec_truncates_5_options() -> None:
    """More than 4 options is truncated to 4 by coercion."""
    q = _question(options=[_opt("A"), _opt("B"), _opt("C"), _opt("D"), _opt("E")])
    assert len(q.options) == 4


def test_question_spec_truncates_header_over_12_chars() -> None:
    """Header longer than 12 chars is truncated, not rejected."""
    q = _question(header="This header is way too long")
    assert len(q.header) == 12
    assert q.header == "This header "


def test_question_spec_truncates_question_over_100_words() -> None:
    """Question longer than 100 words is truncated, not rejected."""
    long_q = " ".join(["word"] * 101)
    q = _question(question=long_q)
    assert len(q.question.split()) == 100


def test_question_spec_dedupes_duplicate_option_labels() -> None:
    """Duplicate option labels are de-duplicated with suffixes."""
    q = _question(options=[_opt("Same"), _opt("Same"), _opt("C")])
    labels = [opt.label for opt in q.options]
    assert len(labels) == len(set(labels))
    assert "Same" in labels
    assert "Same (2)" in labels


# ---------------------------------------------------------------------------
# _AskUserArgs normalization
# ---------------------------------------------------------------------------


def test_args_schema_placeholder_for_empty() -> None:
    """Empty args produces a placeholder question instead of raising."""
    args = _AskUserArgs()
    assert len(args.questions) == 1
    assert args.questions[0].question.strip()


def test_args_schema_placeholder_for_whitespace_only_question() -> None:
    """Whitespace-only questions are replaced with a placeholder."""
    q = _question(question="  ")
    args = _AskUserArgs(questions=[q])
    assert len(args.questions) == 1
    assert args.questions[0].question.strip()


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


def test_args_schema_dedupes_duplicate_question_texts() -> None:
    """Duplicate question texts are de-duplicated, keeping the first."""
    q1 = _question(question="Same question?", header="H1")
    q2 = _question(question="Same question?", header="H2")
    args = _AskUserArgs(questions=[q1, q2])
    assert len(args.questions) == 1
    assert args.questions[0].header == "H1"


# ---------------------------------------------------------------------------
# LLM arg-quirk coercion
# ---------------------------------------------------------------------------


def test_args_schema_coerces_stringified_json_questions() -> None:
    """Questions as stringified JSON array are parsed."""
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
    """Model emitted question fields as top-level tool args are wrapped."""
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
    """Options arriving as a JSON string are parsed."""
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


@pytest.mark.parametrize("marker", ["- ", "* ", "+ "])
def test_args_schema_coerces_markdown_prefixed_options(marker: str) -> None:
    """Options prefixed with a markdown list marker are parsed into a list.

    Reproduces the original user report: an LLM emitted options as
    ``- [{"label": "Dragons", ...}]`` and json.loads() failed on the ``- ``
    prefix, leaving the raw string to be rejected by Pydantic with
    "Input should be a valid list".
    """
    opts_json = json.dumps(
        [
            {"label": "Dragons", "description": "Mythical flying reptiles."},
            {"label": "Unicorns", "description": "Mythical horned horses."},
        ]
    )
    raw = f"{marker}{opts_json}"
    args = _AskUserArgs(
        questions=[{"question": "Q?", "header": "H", "options": raw}],
    )
    assert isinstance(args.questions[0].options, list)
    assert len(args.questions[0].options) == 2
    assert args.questions[0].options[0].label == "Dragons"
    assert isinstance(args.questions[0].options[0], OptionSpec)


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


def test_run_ask_user_all_empty_uses_placeholder() -> None:
    """All-empty questions no longer raise — a placeholder is emitted instead."""
    captured: list[dict[str, Any]] = []

    def fake_interrupt(value: Any) -> Any:
        captured.append(value)
        return {"answers": ["go"]}

    with patch("langgraph.types.interrupt", fake_interrupt):
        result = _run(questions=[_question(question="  ")])

    assert len(captured[0]["questions"]) == 1
    assert captured[0]["questions"][0]["question"].strip()
    assert "A: go" in result


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
