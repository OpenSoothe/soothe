"""LLM-callable ``ask_user`` tool (RFC-622 clarification relay).

When the model invokes this tool, it emits a structured ``ask_user`` LangGraph
interrupt that the :class:`~soothe.sloop.clarification.detector.ClarificationDetector`
captures after the CoreAgent stream ends. The loop then routes to ``AWAIT_USER``
and pauses for a human answer (manual mode) or an auto-answer (veritas, auto
mode). On resume the tool returns the answers so the model can continue the
goal on the same turn.

This is the tool-level counterpart to the planner-emitted ``kind="ask_user"``
step path. Both converge on the same ``pending_clarification`` graph channel.

Use this tool at decision gates (design approval, confirmation gates, routing
menus, ambiguity blockers) rather than writing questions as plain text —
plain-text questions are invisible to the relay and the loop will not pause.
"""

from __future__ import annotations

import logging
from typing import Any

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class _AskUserArgs(BaseModel):
    questions: list[str] = Field(
        ...,
        min_length=1,
        description=(
            "One or more questions to surface to the user. Prefer one question "
            "per call for clarity; use multiple only when the questions form a "
            "single decision unit (e.g. a multi-part routing choice)."
        ),
    )


def _format_answers(questions: list[str], payload: Any) -> str:
    """Render the resume payload as a model-readable answer block.

    The :class:`InteractiveClarificationPolicy` resumes the interrupt with a
    payload shaped by ``_extract_answers`` (``{"answers": [...]}`` or a bare
    string). Accept both and any reasonable variant so the tool is robust to
    relay implementation details.
    """
    answers: list[str]
    if isinstance(payload, str):
        answers = [payload]
    elif isinstance(payload, dict):
        raw = payload.get("answers", payload.get("answer"))
        if isinstance(raw, str):
            answers = [raw]
        elif isinstance(raw, list):
            answers = [str(a) for a in raw]
        else:
            answers = []
    elif isinstance(payload, list):
        answers = [str(a) for a in payload]
    else:
        answers = []

    if not answers:
        return "Clarification dismissed without an answer. Decide how to proceed."
    pairs: list[str] = []
    for idx, question in enumerate(questions):
        ans = answers[idx] if idx < len(answers) else "(no answer)"
        pairs.append(f"Q: {question}\nA: {ans}")
    return "User answered:\n" + "\n".join(pairs)


def _run_ask_user(questions: list[str]) -> str:
    """Emit an ``ask_user`` interrupt and return the answers on resume.

    ``interrupt()`` only works inside a LangGraph node/tool context with a
    checkpointer. When that is the case the call pauses execution here and
    resumes once the user (or veritas) answers. When no checkpointer is
    configured the call raises — degrade to a plain-text fallback so the
    model can still proceed in environments without the relay.
    """
    from langgraph.types import interrupt

    cleaned = [str(q).strip() for q in questions if str(q).strip()]
    if not cleaned:
        return "Error: ask_user requires at least one non-empty question."
    logger.info("[ask_user] LLM asked %d question(s): %s", len(cleaned), cleaned[0][:120])
    try:
        payload = interrupt({"type": "ask_user", "questions": cleaned})
    except Exception:  # pragma: no cover — no-checkpointer environments
        logger.warning(
            "[ask_user] interrupt unavailable (no checkpointer?); falling back",
            exc_info=True,
        )
        return (
            "Clarification relay unavailable in this environment. "
            "State the question in plain text and proceed with the best "
            "assumption, or ask the user to answer directly."
        )
    return _format_answers(cleaned, payload)


async def _arun_ask_user(questions: list[str]) -> str:
    return _run_ask_user(questions)


def build_ask_user_tool() -> StructuredTool:
    """Build the ``ask_user`` LLM-callable clarification tool."""
    return StructuredTool.from_function(
        name="ask_user",
        description=(
            "Ask the user a question and pause the loop until they answer. "
            "Use this at decision gates: design approval, confirmation gates, "
            "routing menus, or when ambiguity blocks progress. Do NOT write "
            "questions as plain text — plain text does not pause the loop and "
            "the user's reply would start a new goal instead of resuming this "
            "one. Prefer one question per call."
        ),
        func=_run_ask_user,
        coroutine=_arun_ask_user,
        args_schema=_AskUserArgs,
        infer_schema=False,
    )
