"""Auto-mode clarification policy backed by the veritas subagent (RFC-622, RFC-623)."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable

from soothe.core.loop.clarification.protocol import (
    ClarificationAnswer,
    ClarificationDeferredError,
    ClarificationPolicy,
    ClarificationRequest,
    DeferKind,
)
from soothe.subagents.veritas.schemas import VeritasAnswerSchema

logger = logging.getLogger(__name__)

VeritasAnswerFn = Callable[[ClarificationRequest], Awaitable[VeritasAnswerSchema]]

_RATIONALE_PREFIX_STRUCTURED = "structured_output_failed"
_RATIONALE_MARKER_QUESTION = "answer_was_question"


class AutoClarificationPolicy:
    """Delegate clarifications to veritas; defer below confidence threshold.

    RFC-623 adds two behaviors on top of the original RFC-622 policy:

    1. Every defer carries a :data:`DeferKind` so operators can distinguish
       legitimate "I don't know" defers from forced ones (LLM glitches).
    2. When ``defer_kind == "structured_output_failed"`` and an
       ``interactive_fallback`` policy is wired, the policy delegates to it
       (durable LangGraph ``interrupt(...)``) instead of terminating the loop.
       The fallback is only present in interactive runs (``emit`` wired);
       autopilot has no human at the other end and keeps the hard-defer path.
    """

    def __init__(
        self,
        veritas_answer: VeritasAnswerFn,
        *,
        min_confidence: float = 0.4,
        interactive_fallback: ClarificationPolicy | None = None,
    ) -> None:
        self._veritas_answer = veritas_answer
        self._min_confidence = min_confidence
        self._interactive_fallback = interactive_fallback

    @property
    def min_confidence(self) -> float:
        return self._min_confidence

    async def answer(self, request: ClarificationRequest) -> ClarificationAnswer:
        result = await self._veritas_answer(request)
        kind = self._classify(result)

        if kind == "structured_output_failed" and self._interactive_fallback is not None:
            logger.warning("[veritas] structured output failed; falling back to interactive relay")
            return await self._interactive_fallback.answer(request)

        if kind is not None:
            raise ClarificationDeferredError(
                self._reason_for(kind, result),
                request,
                kind=kind,
            )

        return ClarificationAnswer(
            answers=tuple(result.answers),
            source="veritas",
            confidence=result.confidence,
            defer=False,
            audit={"rationale": result.rationale},
        )

    def _classify(self, result: VeritasAnswerSchema) -> DeferKind | None:
        """Resolve a veritas result to a :data:`DeferKind`, or ``None`` to accept."""
        if result.defer:
            if result.rationale.startswith(_RATIONALE_PREFIX_STRUCTURED):
                return "structured_output_failed"
            if result.rationale == _RATIONALE_MARKER_QUESTION:
                return "answer_was_question"
            return "explicit"
        if result.confidence < self._min_confidence:
            return "low_confidence"
        return None

    def _reason_for(self, kind: DeferKind, result: VeritasAnswerSchema) -> str:
        if kind == "explicit":
            return f"veritas explicit defer (confidence={result.confidence:.2f})"
        if kind == "low_confidence":
            return f"veritas low confidence ({result.confidence:.2f} < {self._min_confidence:.2f})"
        if kind == "structured_output_failed":
            return f"veritas structured output failed: {result.rationale}"
        if kind == "answer_was_question":
            return "veritas answer was a question"
        return "veritas deferred"


__all__ = ["AutoClarificationPolicy", "VeritasAnswerFn"]
