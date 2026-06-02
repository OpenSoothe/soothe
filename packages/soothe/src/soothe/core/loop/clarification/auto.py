"""Auto-mode clarification policy backed by the veritas subagent (RFC-622)."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable

from soothe.core.loop.clarification.protocol import (
    ClarificationAnswer,
    ClarificationDeferredError,
    ClarificationRequest,
)
from soothe.subagents.veritas.schemas import VeritasAnswerSchema

logger = logging.getLogger(__name__)

VeritasAnswerFn = Callable[[ClarificationRequest], Awaitable[VeritasAnswerSchema]]


class AutoClarificationPolicy:
    """Delegate clarifications to veritas; defer below confidence threshold."""

    def __init__(
        self,
        veritas_answer: VeritasAnswerFn,
        *,
        min_confidence: float = 0.4,
    ) -> None:
        self._veritas_answer = veritas_answer
        self._min_confidence = min_confidence

    @property
    def min_confidence(self) -> float:
        return self._min_confidence

    async def answer(self, request: ClarificationRequest) -> ClarificationAnswer:
        result = await self._veritas_answer(request)

        if result.defer:
            raise ClarificationDeferredError(
                f"veritas explicit defer (confidence={result.confidence:.2f})",
                request,
            )

        if result.confidence < self._min_confidence:
            raise ClarificationDeferredError(
                f"veritas low confidence ({result.confidence:.2f} < {self._min_confidence:.2f})",
                request,
            )

        return ClarificationAnswer(
            answers=tuple(result.answers),
            source="veritas",
            confidence=result.confidence,
            defer=False,
            audit={"rationale": result.rationale},
        )


__all__ = ["AutoClarificationPolicy", "VeritasAnswerFn"]
