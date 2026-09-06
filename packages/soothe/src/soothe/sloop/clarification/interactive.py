"""Interactive (TUI relay) clarification policy."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any

from soothe.sloop.clarification.origins import (
    ORIGIN_TOOL_APPROVAL,
)
from soothe.sloop.clarification.protocol import (
    ClarificationAnswer,
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

        Used when veritas structured output fails and a human is attached.
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

        # Unified relay: don't call LangGraph interrupt(). The relay's park()
        # sees this defer and parks the goal — the graph exits cleanly and
        # is re-invoked when the human answers.
        return ClarificationAnswer(
            answers=(),
            source="human",
            defer=True,
            audit={"defer_kind": "manual", "reason": "awaiting human answer"},
        )

    def _evaluate_tool_approval_pipeline(
        self, request: ClarificationRequest
    ) -> ClarificationAnswer | None:
        """Run the tool-approval pipeline pre-filter for manual mode.

        Returns a static answer when the pipeline resolves the batch, or
        `None` to fall through to the human interrupt. ``escalate`` outcomes
        return ``None`` so the human sees the approval card.
        """
        if request.origin_node != ORIGIN_TOOL_APPROVAL or self._tool_approval_pipeline is None:
            return None
        action_requests = request.metadata.get("action_requests", [])
        result = self._tool_approval_pipeline.evaluate(
            action_requests,
            workspace_root=request.loop_state.workspace_summary,
            auto_approve=self._manual_allow_rules,
            allowlist=list(request.loop_state.tool_approval_allowlist),
        )
        if result is None:
            return None
        # Banned safety action → fall through to the human interrupt so a
        # human decides. Do not auto-resolve.
        if result.decision == "escalate":
            logger.info(
                "[clarification] tool_approval safety escalate rule=%s; routing to human (manual)",
                result.rule_id,
            )
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


__all__ = ["EmitFn", "InteractiveClarificationPolicy"]
