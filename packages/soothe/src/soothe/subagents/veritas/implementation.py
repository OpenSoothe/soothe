"""Veritas auto-answerer: single structured-output LLM call (RFC-622, RFC-623)."""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage
from soothe_nano.llm import StructuredOutputError, ainvoke_structured_traced

from soothe.sloop.clarification.protocol import ClarificationRequest
from soothe.subagents.veritas.prompts import (
    build_veritas_system_prompt_for_origin,
    build_veritas_user_prompt,
)
from soothe.subagents.veritas.schemas import (
    VeritasAnswerSchema,
    build_veritas_response_schema,
    coerce_veritas_response,
)

if TYPE_CHECKING:
    from soothe.config.models import SootheConfig

logger = logging.getLogger(__name__)

_FORCED_DEFER_PREFIX_STRUCTURED = "structured_output_failed"
_FORCED_DEFER_RATIONALE_QUESTION = "answer_was_question"
_FORCED_DEFER_PREFIX_TRANSIENT = "transient_failure"

_QUESTION_PREVIEW_CHARS = 120
_PROMPT_PREVIEW_CHARS = 240

_DEFAULT_MAX_RETRIES = 2
_DEFAULT_RETRY_BACKOFF_SECONDS = 2.0


async def answer(
    request: ClarificationRequest,
    *,
    model: BaseChatModel,
    max_context_steps: int = 8,
    soothe_config: SootheConfig | None = None,
    thread_id: str | None = None,
    loop_id: str | None = None,
    max_retries: int = _DEFAULT_MAX_RETRIES,
    retry_backoff_seconds: float = _DEFAULT_RETRY_BACKOFF_SECONDS,
    coerced_confidence: float = 0.7,
) -> VeritasAnswerSchema:
    """Produce a clarification answer grounded in goal intent and global context.

    Args:
        request: The pending clarification.
        model: A langchain chat model. Veritas drives it through the shared
            ``invoke_structured_chat`` helper which iterates structured-output
            methods for thinking-model compatibility.
        max_context_steps: Cap on recent step outputs included in the user prompt.
        soothe_config: Optional config; when provided, the structured-output call
            is wrapped in a Langfuse-traced RunnableConfig so the veritas span
            shows up under the parent loop graph trace.
        thread_id: Loop thread id; forwarded as Langfuse ``session_id`` and
            recorded in debug logs.
        loop_id: Loop identifier for Langfuse trace correlation across sub-traces.
        max_retries: Max retry attempts for transient infrastructure failures
            (rate limit, timeout, connection error). ``StructuredOutputError``
            (model output malformed) still defers immediately. Set to ``0`` to
            disable retries. Default ``2``.
        retry_backoff_seconds: Base backoff for exponential retry
            (``backoff * 2**attempt``). Default ``2.0`` seconds.
        coerced_confidence: Confidence value assigned when the model returns
            answers but omits ``confidence``. Default ``0.7``.

    Returns:
        Validated :class:`VeritasAnswerSchema`. When the LLM call fails or its
        output cannot satisfy the per-request schema, the result is coerced to
        ``defer=True`` with a rationale prefix (``structured_output_failed: ...``
        or ``transient_failure: ...``) so the policy can populate ``DeferKind``
        and route the recovery path.

    Notes:
        Any answer the model self-classifies as a question (``answer_is_question``
        field) is collapsed to ``defer=True`` with
        ``rationale="answer_was_question"`` so the policy classifies it as a
        forced defer (LLM glitch) rather than a genuine "I don't know." As a
        transitional safety net, the legacy ``endswith("?")`` regex check is
        used when the model omits the ``answer_is_question`` field.
    """
    view = request.loop_state
    n = len(request.questions)

    logger.debug(
        "[veritas] answer() goal_id=%s origin=%s questions=%d iter=%d "
        "context_steps=%d active_skills=%d thread_id=%s",
        view.goal_id,
        request.origin_node,
        n,
        view.iteration,
        len(view.recent_step_outputs),
        len(view.active_skills),
        thread_id or "<none>",
    )
    logger.debug("[veritas] questions: %s", _preview_questions(request.questions))

    json_schema = build_veritas_response_schema(n)
    system_prompt = build_veritas_system_prompt_for_origin(request.origin_node)
    user_prompt = build_veritas_user_prompt(request, max_context_steps=max_context_steps)
    messages = [
        SystemMessage(content=system_prompt),
        HumanMessage(content=user_prompt),
    ]

    logger.debug(
        "[veritas] prompt sizes: system=%d chars user=%d chars",
        len(system_prompt),
        len(user_prompt),
    )
    logger.debug("[veritas] user prompt preview: %s", _truncate(user_prompt, _PROMPT_PREVIEW_CHARS))

    trace_name = (
        (soothe_config.observability.langfuse.trace_name or "").strip()
        if soothe_config is not None
        else ""
    )
    data: dict[str, Any] | None = None
    last_exc: Exception | None = None

    for attempt in range(max_retries + 1):
        try:
            data = await ainvoke_structured_traced(
                model,
                messages,
                json_schema=json_schema,
                schema_name="VeritasAnswer",
                strict=True,
                soothe_config=soothe_config,
                purpose="clarification_answer",
                component="subagent.veritas",
                phase="pre-stream",
                session_id=thread_id,
                loop_id=loop_id,
                run_name=f"{trace_name}:veritas" if trace_name else "veritas",
                normalize=lambda value: coerce_veritas_response(
                    value,
                    n,
                    coerced_confidence=coerced_confidence,
                ),
            )
            break
        except StructuredOutputError as exc:
            logger.warning("[veritas] structured output failed: %s", exc)
            return VeritasAnswerSchema(
                defer=True,
                confidence=0.0,
                rationale=f"{_FORCED_DEFER_PREFIX_STRUCTURED}: {exc}",
                answers=[],
            )
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            if attempt < max_retries:
                backoff = retry_backoff_seconds * (2**attempt)
                logger.warning(
                    "[veritas] transient failure (attempt %d/%d): %s; retrying in %.1fs",
                    attempt + 1,
                    max_retries + 1,
                    exc,
                    backoff,
                )
                await asyncio.sleep(backoff)
            else:
                logger.warning(
                    "[veritas] transient failure exhausted retries (%d/%d): %s",
                    attempt + 1,
                    max_retries + 1,
                    exc,
                )

    if data is None:
        return VeritasAnswerSchema(
            defer=True,
            confidence=0.0,
            rationale=f"{_FORCED_DEFER_PREFIX_TRANSIENT}: {last_exc}",
            answers=[],
        )

    result = VeritasAnswerSchema.model_validate(data)
    logger.debug(
        "[veritas] result defer=%s confidence=%.2f answers=%d rationale=%s",
        result.defer,
        result.confidence,
        len(result.answers),
        _truncate(result.rationale, _QUESTION_PREVIEW_CHARS),
    )
    if result.reasoning:
        logger.debug(
            "[veritas] reasoning: %s", _truncate(result.reasoning, _QUESTION_PREVIEW_CHARS)
        )

    if not result.defer and _any_answer_is_a_question(result.answers, result.answer_is_question):
        logger.info("[veritas] answer classified as question; coercing to defer")
        return result.model_copy(
            update={
                "defer": True,
                "confidence": 0.0,
                "rationale": _FORCED_DEFER_RATIONALE_QUESTION,
            }
        )

    return result


def _any_answer_is_a_question(
    answers: list[str],
    answer_is_question: list[bool] | None = None,
) -> bool:
    """Detect whether any answer is itself a question (RFC-630 compliance).

    Prefers the model's structured self-classification (``answer_is_question``
    field) when available. Falls back to the legacy ``endswith("?")`` regex
    check when the model omits the field — a transitional safety net that will
    be removed once all models reliably emit the structured field.
    """
    if answer_is_question:
        return any(answer_is_question)
    # Transitional fallback: ?-suffix heuristic (to be removed post-migration).
    return any(a.strip().endswith("?") for a in answers)


def _preview_questions(questions: tuple) -> str:
    # RFC-622 §9c: questions may be QuestionSpec.model_dump() dicts, not just strings.
    return " | ".join(_truncate(_question_text(q), _QUESTION_PREVIEW_CHARS) for q in questions)


def _question_text(question: Any) -> str:
    """Render a structured question (RFC-622 §9c) or plain string as text."""
    if isinstance(question, dict):
        return str(question.get("question") or question.get("header") or "")
    return str(question)


def _truncate(text: str, limit: int) -> str:
    s = text.strip()
    if len(s) <= limit:
        return s
    return s[: limit - 1] + "…"


__all__ = ["answer"]
