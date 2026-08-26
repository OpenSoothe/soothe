"""``ask_user`` tool — pauses the loop for a human answer (RFC-622)."""

from __future__ import annotations

import logging

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field, model_validator

logger = logging.getLogger(__name__)


class _AskUserArgs(BaseModel):
    """``questions`` (list) is primary; ``question`` (str) is a singular alias."""

    questions: list[str] = Field(
        default_factory=list,
        description="The question(s) to ask the user.",
    )
    question: str | None = Field(
        default=None,
        description="Single-question shorthand for 'questions'.",
    )

    @model_validator(mode="after")
    def _normalize(self) -> _AskUserArgs:
        if not self.questions and self.question:
            self.questions = [self.question]
        if not self.questions:
            raise ValueError("ask_user requires 'questions' or 'question'")
        return self


def _format_answers(questions: list[str], payload: object) -> str:
    """Render the resume payload as a model-readable Q&A block."""
    raw = payload.get("answers", payload) if isinstance(payload, dict) else payload
    answers = (
        [raw] if isinstance(raw, str) else [str(a) for a in raw] if isinstance(raw, list) else []
    )
    if not answers:
        return "Clarification dismissed without an answer. Decide how to proceed."
    pairs = [
        f"Q: {q}\nA: {answers[i] if i < len(answers) else '(no answer)'}"
        for i, q in enumerate(questions)
    ]
    return "User answered:\n" + "\n".join(pairs)


def _run_ask_user(
    questions: list[str] | None = None,
    *,
    question: str | None = None,
) -> str:
    """Pause the graph via ``interrupt()``; return formatted answers on resume."""
    from langgraph.types import interrupt

    qs = list(questions or [])
    if not qs and question:
        qs = [question]
    cleaned = [str(q).strip() for q in qs if str(q).strip()]
    if not cleaned:
        return "Error: ask_user requires at least one non-empty question."
    logger.info("[ask_user] LLM asked %d question(s): %s", len(cleaned), cleaned[0][:120])
    payload = interrupt({"type": "ask_user", "questions": cleaned})
    return _format_answers(cleaned, payload)


async def _arun_ask_user(
    questions: list[str] | None = None,
    *,
    question: str | None = None,
) -> str:
    return _run_ask_user(questions, question=question)


def build_ask_user_tool() -> StructuredTool:
    """Build the ``ask_user`` StructuredTool."""
    return StructuredTool.from_function(
        name="ask_user",
        description=(
            "Ask the user a question and pause the loop until they answer. "
            "Use 'question' (string) or 'questions' (list). For decision gates: "
            "approval, confirmation, routing, or resolving ambiguity. "
            "Plain-text questions do not pause the loop."
        ),
        func=_run_ask_user,
        coroutine=_arun_ask_user,
        args_schema=_AskUserArgs,
        infer_schema=False,
    )
