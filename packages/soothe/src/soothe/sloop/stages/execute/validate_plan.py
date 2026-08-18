"""Deterministic evidence binding validation (RFC-220 ``validate_evidence_bindings``).

Migrated to ``LoopNode`` (RFC-903 P2): the node is a ``ValidatePlanNode``
subclass. The fatal guard (missing ``scratch.decision``) moves into ``pre``
via ``GuardOutcome``; the validation failure returns ``RouteDecision(kind="fatal")``.
The legacy ``node_validate_evidence_bindings`` function is retained as a thin
wrapper.
"""

from __future__ import annotations

import logging
from typing import Any

from soothe.sloop.orchestrator.evidence import validate_plan_evidence
from soothe.sloop.orchestrator.node_base import GuardOutcome, LoopNode, NodeResult, RouteDecision
from soothe.sloop.orchestrator.runtime_context import LoopRuntimeContext

logger = logging.getLogger(__name__)


class ValidatePlanNode(LoopNode):
    """Reject plans whose steps lack valid evidence refs when the ledger is non-empty.

    Non-LLM node (``call_kind is None``). The missing-decision guard is in
    ``pre`` (returns ``GuardOutcome(kind="fatal")``); the validation failure
    is in ``process`` returning a ``NodeResult`` whose payload signals fatal.
    """

    station = "validate_plan"
    call_kind = None

    async def pre(self, ctx: LoopRuntimeContext, state: dict[str, Any]) -> GuardOutcome | None:
        decision = ctx.scratch.decision
        if decision is None:
            logger.error("[validate_evidence_bindings] missing scratch.decision")
            await ctx.emit(
                "fatal_error",
                {"error": "Evidence validation without decision", "step_id": ""},
            )
            return GuardOutcome(kind="fatal")
        return None

    async def process(
        self,
        ctx: LoopRuntimeContext,
        state: dict[str, Any],
        messages: list,
    ) -> NodeResult:
        strange_loop = ctx.strange_loop
        loop_state = ctx.loop_state
        decision = ctx.scratch.decision

        if not validate_plan_evidence(strange_loop.config, loop_state, decision):
            logger.error("[Plan] Evidence validation failed for planned steps")
            return NodeResult(
                payload=None,
                events=[
                    ("fatal_error", {"error": "Plan evidence validation failed", "step_id": ""})
                ],
            )

        return NodeResult(payload=decision)

    def post(
        self,
        ctx: LoopRuntimeContext,
        state: dict[str, Any],
        result: NodeResult,
    ) -> RouteDecision:
        # If process returned events with fatal_error, the payload is None.
        if result.payload is None:
            return RouteDecision(kind="fatal")
        return RouteDecision(kind="proceed")


# Singleton instance for the graph builder.
node: ValidatePlanNode = ValidatePlanNode()


async def node_validate_evidence_bindings(
    ctx: LoopRuntimeContext, _state: dict[str, Any]
) -> dict[str, Any]:
    """Legacy entry point — delegates to :class:`ValidatePlanNode`."""
    return await node(ctx, _state)
