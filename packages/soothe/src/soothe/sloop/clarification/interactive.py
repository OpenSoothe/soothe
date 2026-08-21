"""Interactive (TUI relay) clarification policy (RFC-622).

The policy pauses the loop graph at a LangGraph ``interrupt(...)`` call. The
checkpoint snapshot captures the pending question, so TUI close/reopen and
daemon restart both restore the loop at the same point. When the TUI submits
the answer via ``Command(resume=...)``, ``interrupt(...)`` returns the payload
and the policy unwraps it into a :class:`ClarificationAnswer`.

``await_clarification`` owns the primary ``clarification_requested`` emit
(with the correct mode). This policy only re-announces when used as an
auto→manual upgrade (RFC-623 structured-output failure), via
:meth:`answer_as_manual_fallback`.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from langgraph.types import interrupt

from soothe.sloop.clarification.origins import ORIGIN_PLAN_MODE_REVIEW
from soothe.sloop.clarification.protocol import (
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
        """Pause for a human answer without re-emitting ``clarification_requested``.

        ``await_clarification`` already emitted the request (including
        ``force_manual_origins`` with ``mode=manual``). Re-emitting here would
        duplicate events for every interactive pause.
        """
        return await self._answer(request, announce=False)

    async def answer_as_manual_fallback(self, request: ClarificationRequest) -> ClarificationAnswer:
        """Re-announce as ``mode=manual`` then pause (auto→manual upgrade).

        Used when veritas structured output fails and a human is attached
        (RFC-623). The earlier ``await_clarification`` emit used ``mode=auto``.
        """
        return await self._answer(request, announce=True)

    async def _answer(
        self, request: ClarificationRequest, *, announce: bool
    ) -> ClarificationAnswer:
        if announce and self._emit is not None:
            await self._emit(
                "clarification_requested",
                {
                    "questions": list(request.questions),
                    "origin_node": request.origin_node,
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

        answers = self._extract_answers(
            payload, expected=len(request.questions), origin=request.origin_node
        )
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
    def _extract_answers(
        payload: Any, *, expected: int, origin: str | None = None
    ) -> list[str] | None:
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

        stripped = [a.strip() for a in answers]

        # Plan-mode review asks two questions (action + revision comments), but
        # only the action field is required — the revision-comments field is
        # only meaningful for the "comments" action and is legitimately blank
        # for approve/reject. Treat it as answered when the action field (index
        # 0) is non-empty; pad the optional trailing field instead of
        # dismissing the whole answer as "no answer" (RFC-904 plan-mode review).
        if origin == ORIGIN_PLAN_MODE_REVIEW and expected == 2:
            if stripped and stripped[0]:
                # Pad / truncate to the expected length so downstream parsers
                # that index answers[1] always see a string.
                if len(stripped) == 1:
                    stripped.append("")
                return stripped[:expected]
            return None

        if any(not a for a in stripped):
            return None

        if len(stripped) == expected:
            return stripped
        if len(stripped) == 1 and expected > 1:
            # broadcast single answer when caller didn't split per-question
            return stripped * expected
        return None


__all__ = ["EmitFn", "InteractiveClarificationPolicy"]
