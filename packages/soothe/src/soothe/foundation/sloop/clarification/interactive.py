"""Interactive (TUI relay) clarification policy (RFC-622).

The policy pauses the loop graph at a LangGraph ``interrupt(...)`` call. The
checkpoint snapshot captures the pending question, so TUI close/reopen and
daemon restart both restore the loop at the same point. When the TUI submits
the answer via ``Command(resume=...)``, ``interrupt(...)`` returns the payload
and the policy unwraps it into a :class:`ClarificationAnswer`.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from langgraph.types import interrupt

from soothe.foundation.sloop.clarification.protocol import (
    ClarificationAnswer,
    ClarificationDeferredError,
    ClarificationRequest,
)

EmitFn = Callable[[str, dict[str, Any]], Awaitable[None]]


class InteractiveClarificationPolicy:
    """Relay clarifications to a human via the TUI; loop-level durable pause."""

    def __init__(self, emit: EmitFn | None = None) -> None:
        self._emit = emit

    def bind_emit(self, emit: EmitFn) -> None:
        """Attach the runtime emit callback (RFC-623 interactive fallback wiring)."""
        self._emit = emit

    async def answer(self, request: ClarificationRequest) -> ClarificationAnswer:
        if self._emit is not None:
            await self._emit(
                "clarification_requested",
                {
                    "questions": list(request.questions),
                    "origin": request.origin_node,
                    "mode": "manual",
                },
            )

        payload = interrupt(
            {
                "type": "clarification",
                "interrupt_id": request.origin_interrupt_id,
                "questions": list(request.questions),
            }
        )

        answers = self._extract_answers(payload, expected=len(request.questions))
        if answers is None:
            raise ClarificationDeferredError(
                "operator dismissed clarification (no answer)",
                request,
                kind="explicit",
            )

        return ClarificationAnswer(
            answers=tuple(answers),
            source="human",
        )

    @staticmethod
    def _extract_answers(payload: Any, *, expected: int) -> list[str] | None:
        if payload is None:
            return None
        if isinstance(payload, str):
            answers = [payload]
        elif isinstance(payload, dict):
            raw = payload.get("answers", payload.get("answer"))
            if raw is None:
                return None
            if isinstance(raw, str):
                answers = [raw]
            elif isinstance(raw, list):
                answers = [str(a) for a in raw]
            else:
                return None
        elif isinstance(payload, list):
            answers = [str(a) for a in payload]
        else:
            return None

        if len(answers) == expected:
            return answers
        if len(answers) == 1 and expected > 1:
            # broadcast single answer when caller didn't split per-question
            return answers * expected
        return None


__all__ = ["EmitFn", "InteractiveClarificationPolicy"]
