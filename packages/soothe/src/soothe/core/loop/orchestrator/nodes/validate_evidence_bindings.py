"""Deterministic evidence binding validation (RFC-220 ``validate_evidence_bindings``)."""

from __future__ import annotations

import logging
from typing import Any

from soothe.core.loop.orchestrator.evidence import validate_plan_evidence

from ..runtime_context import LoopRuntimeContext

logger = logging.getLogger(__name__)


async def node_validate_evidence_bindings(
    ctx: LoopRuntimeContext, _state: dict[str, Any]
) -> dict[str, Any]:
    """Reject plans whose steps lack valid evidence refs when the ledger is non-empty."""
    agent_loop = ctx.agent_loop
    state = ctx.loop_state
    decision = ctx.scratch.decision

    if decision is None:
        logger.error("[validate_evidence_bindings] missing scratch.decision")
        await ctx.emit(
            "fatal_error",
            {"error": "Evidence validation without decision", "step_id": ""},
        )
        return {"last_outcome": "fatal"}

    if not validate_plan_evidence(agent_loop.config, state, decision):
        logger.error("[Plan] Evidence validation failed for planned steps")
        await ctx.emit(
            "fatal_error",
            {
                "error": "Plan evidence validation failed",
                "step_id": "",
            },
        )
        return {"last_outcome": "fatal"}

    return {}
