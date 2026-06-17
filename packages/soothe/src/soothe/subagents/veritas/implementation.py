"""Veritas auto-answerer: single structured-output LLM call (RFC-622, RFC-623)."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage

from soothe.foundation.loop.clarification.protocol import ClarificationRequest
from soothe.subagents.veritas.prompts import (
    build_veritas_system_prompt,
    build_veritas_user_prompt,
)
from soothe.subagents.veritas.schemas import (
    VeritasAnswerSchema,
    build_veritas_response_schema,
)
from soothe.utils.llm.structured import (
    StructuredOutputError,
    invoke_structured_chat,
)

if TYPE_CHECKING:
    from soothe.config.models import SootheConfig

logger = logging.getLogger(__name__)

_FORCED_DEFER_PREFIX_STRUCTURED = "structured_output_failed"
_FORCED_DEFER_RATIONALE_QUESTION = "answer_was_question"

_QUESTION_PREVIEW_CHARS = 120
_PROMPT_PREVIEW_CHARS = 240


async def answer(
    request: ClarificationRequest,
    *,
    model: BaseChatModel,
    max_context_steps: int = 8,
    soothe_config: SootheConfig | None = None,
    thread_id: str | None = None,
    loop_id: str | None = None,
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
    system_prompt = build_veritas_system_prompt()
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

    invoke_config = _build_traced_invoke_config(
        soothe_config=soothe_config, thread_id=thread_id, loop_id=loop_id
    )

    try:
        data = await invoke_structured_chat(
            model,
            messages,
            json_schema=json_schema,
            schema_name="VeritasAnswer",
            strict=True,
            config=invoke_config,
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
    logger.debug(
        "[veritas] result defer=%s confidence=%.2f answers=%d rationale=%s",
        result.defer,
        result.confidence,
        len(result.answers),
        _truncate(result.rationale, _QUESTION_PREVIEW_CHARS),
    )

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


def _preview_questions(questions: tuple[str, ...]) -> str:
    return " | ".join(_truncate(q, _QUESTION_PREVIEW_CHARS) for q in questions)


def _truncate(text: str, limit: int) -> str:
    s = text.strip()
    if len(s) <= limit:
        return s
    return s[: limit - 1] + "…"


def _build_traced_invoke_config(
    *,
    soothe_config: SootheConfig | None,
    thread_id: str | None,
    loop_id: str | None,
) -> dict[str, Any] | None:
    """Wrap the veritas LLM call in a Langfuse-traced RunnableConfig.

    Returns ``None`` when no config is provided (e.g. unit tests) or when
    Langfuse construction fails — the helper accepts ``None`` and the call
    still goes through.
    """
    if soothe_config is None:
        return None
    try:
        from soothe.utils.observability.langfuse import build_traced_config

        trace_name = (soothe_config.observability.langfuse.trace_name or "").strip()
        run_name = f"{trace_name}:veritas" if trace_name else "veritas"
        return build_traced_config(
            soothe_config,
            purpose="clarification_answer",
            component="subagent.veritas",
            phase="pre-stream",
            session_id=thread_id,
            loop_id=loop_id,
            run_name=run_name,
        )
    except Exception:
        logger.debug("[veritas] failed to build Langfuse traced config", exc_info=True)
        return None


__all__ = ["answer"]
