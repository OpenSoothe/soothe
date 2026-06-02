"""Veritas auto-answerer: single structured-output LLM call (RFC-622)."""

from __future__ import annotations

import logging

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage

from soothe.core.loop.clarification.protocol import ClarificationRequest
from soothe.subagents.veritas.prompts import (
    build_veritas_system_prompt,
    build_veritas_user_prompt,
)
from soothe.subagents.veritas.schemas import VeritasAnswerSchema

logger = logging.getLogger(__name__)


async def answer(
    request: ClarificationRequest,
    *,
    model: BaseChatModel,
    max_context_steps: int = 8,
) -> VeritasAnswerSchema:
    """Produce a clarification answer grounded in goal intent and global context.

    Args:
        request: The pending clarification.
        model: A langchain chat model configured for structured output.
        max_context_steps: Cap on recent step outputs included in the user prompt.

    Returns:
        Validated :class:`VeritasAnswerSchema` from the model.

    Notes:
        Any answer that ends with a question mark is collapsed to ``defer=True``
        with ``confidence=0.0`` so the loop falls back to the defer path
        instead of recursing into another clarification.
    """
    structured = model.with_structured_output(VeritasAnswerSchema)
    system_prompt = build_veritas_system_prompt()
    user_prompt = build_veritas_user_prompt(request, max_context_steps=max_context_steps)

    result = await structured.ainvoke(
        [
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_prompt),
        ]
    )

    if not isinstance(result, VeritasAnswerSchema):
        msg = f"unexpected structured-output type: {type(result).__name__}"
        raise TypeError(msg)

    if _any_answer_is_a_question(result.answers):
        logger.info("[veritas] answer ended with '?'; coercing to defer")
        return result.model_copy(update={"defer": True, "confidence": 0.0})

    if len(result.answers) != len(request.questions):
        logger.info(
            "[veritas] answer count mismatch (got %d, want %d); coercing to defer",
            len(result.answers),
            len(request.questions),
        )
        return result.model_copy(update={"defer": True, "confidence": 0.0})

    return result


def _any_answer_is_a_question(answers: list[str]) -> bool:
    return any(a.strip().endswith("?") for a in answers)


__all__ = ["answer"]
