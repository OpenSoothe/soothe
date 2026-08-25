"""LLM-callable ``ask_user`` tool (RFC-622 clarification relay).

When the model invokes this tool, ``interrupt()`` raises ``GraphInterrupt``
to pause the graph. The executor's stream loop catches it and routes to
``AWAIT_USER``. When the user answers via ``Command(resume=...)``, the graph
re-enters here, ``interrupt()`` returns the resume payload, and this function
renders the answers for the model.
"""

from __future__ import annotations

import logging

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field, model_validator

logger = logging.getLogger(__name__)


class _AskUserArgs(BaseModel):
    """Arguments for ``ask_user``.

    ``questions`` is the primary field (list of strings). ``query`` is a
    convenience alias — models frequently send a single string as ``query``
    on the first call instead of a list as ``questions``.
    """

    questions: list[str] = Field(
        default_factory=list,
        description="The question(s) to ask the user. List of strings.",
    )
    query: str | None = Field(
        default=None,
        description="Alternative to 'questions': a single question as a string.",
    )

    @model_validator(mode="after")
    def _normalize(self) -> _AskUserArgs:
        if not self.questions and self.query:
            self.questions = [self.query]
        if not self.questions:
            raise ValueError("ask_user requires at least one question (use 'questions' or 'query')")
        return self


def _format_answers(questions: list[str], payload: object) -> str:
    """Render the resume payload as a model-readable answer block."""
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


def _run_ask_user(questions: list[str] | None = None, *, query: str | None = None) -> str:
    """Emit an ``ask_user`` interrupt and return the answers on resume."""
    from langgraph.types import interrupt

    qs = list(questions or [])
    if not qs and query:
        qs = [query]
    cleaned = [str(q).strip() for q in qs if str(q).strip()]
    if not cleaned:
        return "Error: ask_user requires at least one non-empty question."
    logger.info("[ask_user] LLM asked %d question(s): %s", len(cleaned), cleaned[0][:120])
    payload = interrupt({"type": "ask_user", "questions": cleaned})
    return _format_answers(cleaned, payload)


async def _arun_ask_user(questions: list[str] | None = None, *, query: str | None = None) -> str:
    return _run_ask_user(questions, query=query)


def build_ask_user_tool() -> StructuredTool:
    """Build the ``ask_user`` LLM-callable clarification tool."""
    return StructuredTool.from_function(
        name="ask_user",
        description=(
            "Ask the user a question and pause the loop until they answer. "
            "Pass your question as a string in the 'query' field, or as a list "
            "of strings in the 'questions' field. "
            "Use this at decision gates: design approval, confirmation gates, "
            "routing menus, or when ambiguity blocks progress. Do NOT write "
            "questions as plain text — plain text does not pause the loop."
        ),
        func=_run_ask_user,
        coroutine=_arun_ask_user,
        args_schema=_AskUserArgs,
        infer_schema=False,
    )
