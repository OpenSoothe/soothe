"""Interactive (TUI relay) clarification policy."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any

from langgraph.types import interrupt

from soothe.sloop.clarification.origins import (
    ORIGIN_PLAN_MODE_REVIEW,
    ORIGIN_TOOL_APPROVAL,
)
from soothe.sloop.clarification.protocol import (
    ClarificationAnswer,
    ClarificationDeferredError,
    ClarificationRequest,
)
from soothe.sloop.clarification.tool_approval_pipeline import (
    ToolApprovalPipeline,
)

EmitFn = Callable[[str, dict[str, Any]], Awaitable[None]]

logger = logging.getLogger(__name__)


class InteractiveClarificationPolicy:
    """Relay clarifications to a human via the TUI; loop-level durable pause.

    When a `ToolApprovalPipeline` is attached (manual clarification mode,
    ), it pre-filters `tool_approval` requests: deny/safety
    stages always auto-reject dangerous actions without asking the human,
    and allow rules auto-approve when `manual_allow_rules` is set
    (`tool_approval.manual_scope: ambiguous_only`). Only rule-unresolved
    actions reach the human. The pre-filter does not run on the
    auto→manual upgrade path — the auto policy already evaluated the
    pipeline before deferring to this policy as fallback.
    """

    def __init__(
        self,
        emit: EmitFn | None = None,
        *,
        tool_approval_pipeline: ToolApprovalPipeline | None = None,
        manual_allow_rules: bool = False,
    ) -> None:
        self._emit = emit
        self._tool_approval_pipeline = tool_approval_pipeline
        self._manual_allow_rules = manual_allow_rules

    def bind_emit(self, emit: EmitFn) -> None:
        """Attach the runtime emit callback."""
        self._emit = emit

    async def answer(self, request: ClarificationRequest) -> ClarificationAnswer:
        """Pause for a human answer without re-emitting `clarification_requested`.

        `await_clarification` already emitted the request (including
        `force_manual_origins` with `mode=manual`). Re-emitting here would
        duplicate events for every interactive pause.
        """
        static = self._evaluate_tool_approval_pipeline(request)
        if static is not None:
            return static
        return await self._answer(request, announce=False)

    async def answer_as_manual_fallback(self, request: ClarificationRequest) -> ClarificationAnswer:
        """Re-announce as `mode=manual` then pause (auto→manual upgrade).

                Used when veritas structured output fails and a human is attached
        The earlier `await_clarification` emit used `mode=auto`.
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

    def _evaluate_tool_approval_pipeline(
        self, request: ClarificationRequest
    ) -> ClarificationAnswer | None:
        """Run the tool-approval pipeline pre-filter for manual mode (§9b).

        Returns a static answer when the pipeline resolves the batch, or
        `None` to fall through to the human interrupt.
        """
        if request.origin_node != ORIGIN_TOOL_APPROVAL or self._tool_approval_pipeline is None:
            return None
        action_requests = request.metadata.get("action_requests", [])
        result = self._tool_approval_pipeline.evaluate(
            action_requests,
            workspace_root=request.loop_state.workspace_summary,
            auto_approve=self._manual_allow_rules,
        )
        if result is None:
            return None
        logger.info(
            "[clarification] tool_approval %s by stage=%s reason=%s (manual pre-filter)",
            result.decision,
            result.stage,
            result.reason,
        )
        return ClarificationAnswer(
            answers=(result.decision,),
            source="static",
            confidence=1.0,
            audit={"stage": result.stage, "reason": result.reason},
        )

    @staticmethod
    def _extract_answers(
        payload: Any, *, expected: int, origin: str | None = None
    ) -> list[str] | None:
        stripped = InteractiveClarificationPolicy._normalize_payload(payload)
        if stripped is None:
            return None

        # Action-selector origins (plan-mode review, tool approval) send
        # [action, optional-comment]; only the action field (index 0) is
        # required — the trailing comment is legitimately blank (approve) or
        # carries edit args. Treat a non-empty action as answered and pad /
        # truncate to the expected length instead of dismissing the whole
        # answer (the TUI always submits both slots).
        if (
            origin in (ORIGIN_PLAN_MODE_REVIEW, ORIGIN_TOOL_APPROVAL)
            and expected in (1, 2)
            and stripped
            and stripped[0]
        ):
            if len(stripped) == 1:
                stripped.append("")
            return stripped[:expected]

        if any(not a for a in stripped):
            return None

        if len(stripped) == expected:
            return stripped
        if len(stripped) == 1 and expected > 1:
            # broadcast single answer when caller didn't split per-question
            return stripped * expected
        return None

    @staticmethod
    def _normalize_payload(payload: Any) -> list[str] | None:
        """Extract a raw answer list from an interrupt payload.

        Returns stripped strings, or `None` when the payload is empty or
        has an unrecognizable shape.
        """
        if payload is None:
            return None
        if isinstance(payload, str):
            raw = [payload]
        elif isinstance(payload, dict):
            val = payload.get("answers", payload.get("answer"))
            if val is None:
                return None
            if isinstance(val, str):
                raw = [val]
            elif isinstance(val, list):
                raw = [str(a) for a in val]
            else:
                return None
        elif isinstance(payload, list):
            raw = [str(a) for a in payload]
        else:
            return None
        return [a.strip() for a in raw]


__all__ = ["EmitFn", "InteractiveClarificationPolicy"]
