"""Veritas auto-answerer: single structured-output LLM call (RFC-622, RFC-623)."""

from __future__ import annotations

import logging

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage

from soothe.core.loop.clarification.protocol import ClarificationRequest
from soothe.subagents.veritas.prompts import (
    build_veritas_system_prompt,
    build_veritas_user_prompt,
)
from soothe.subagents.veritas.schemas import (
    VeritasAnswerSchema,
    build_veritas_response_schema,
)
from soothe.utils.llm.structured_invoke import (
    StructuredOutputError,
    invoke_structured_chat,
)

logger = logging.getLogger(__name__)

_FORCED_DEFER_PREFIX_STRUCTURED = "structured_output_failed"
_FORCED_DEFER_RATIONALE_QUESTION = "answer_was_question"


async def answer(
    request: ClarificationRequest,
    *,
    model: BaseChatModel,
    max_context_steps: int = 8,
) -> VeritasAnswerSchema:
    """Produce a clarification answer grounded in goal intent and global context.

    Args:
        request: The pending clarification.
        model: A langchain chat model. Veritas drives it through the shared
            ``invoke_structured_chat`` helper which iterates structured-output
            methods for thinking-model compatibility.
        max_context_steps: Cap on recent step outputs included in the user prompt.

    Returns:
        Validated :class:`VeritasAnswerSchema`. When the LLM call fails or its
        output cannot satisfy the per-request schema, the result is coerced to
        ``defer=True`` with a rationale prefix (``structured_output_failed: ...``)
        so the policy can populate ``DeferKind`` and route the recovery path.

    Notes:
        Any answer ending in ``?`` is collapsed to ``defer=True`` with
        ``rationale="answer_was_question"`` so the policy classifies it as a
        forced defer (LLM glitch) rather than a genuine "I don't know."
    """
    n = len(request.questions)
    json_schema = build_veritas_response_schema(n)
    messages = [
        SystemMessage(content=build_veritas_system_prompt()),
        HumanMessage(
            content=build_veritas_user_prompt(request, max_context_steps=max_context_steps)
        ),
    ]

    try:
        data = await invoke_structured_chat(
            model,
            messages,
            json_schema=json_schema,
            schema_name="VeritasAnswer",
            strict=True,
        )
    except StructuredOutputError as exc:
        logger.warning("[veritas] structured output failed: %s", exc)
        return VeritasAnswerSchema(
            defer=True,
            confidence=0.0,
            rationale=f"{_FORCED_DEFER_PREFIX_STRUCTURED}: {exc}",
            answers=[],
        )

    result = VeritasAnswerSchema.model_validate(data)

    if not result.defer and _any_answer_is_a_question(result.answers):
        logger.info("[veritas] answer ended with '?'; coercing to defer")
        return result.model_copy(
            update={
                "defer": True,
                "confidence": 0.0,
                "rationale": _FORCED_DEFER_RATIONALE_QUESTION,
            }
        )

    return result


def _any_answer_is_a_question(answers: list[str]) -> bool:
    return any(a.strip().endswith("?") for a in answers)


__all__ = ["answer"]
