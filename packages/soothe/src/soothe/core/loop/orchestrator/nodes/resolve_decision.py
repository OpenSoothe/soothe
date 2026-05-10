"""Resolve executable ``AgentDecision`` from ``PlanResult`` (RFC-220 pre-execute path)."""

from __future__ import annotations

import logging
from typing import Any

from soothe.core.loop.state.schemas import allocate_plan_id, assign_plan_step_ids
from soothe.utils.text_preview import preview_first

from ..runtime_context import LoopRuntimeContext

logger = logging.getLogger(__name__)


async def node_resolve_decision(ctx: LoopRuntimeContext, _state: dict[str, Any]) -> dict[str, Any]:
    """Allocate plan ids, merge keep/new semantics, stash decision on scratch."""
    agent_loop = ctx.agent_loop
    state = ctx.loop_state
    plan_result = ctx.scratch.plan_result

    if plan_result is None:
        logger.error("[resolve_decision] missing scratch.plan_result")
        await ctx.emit(
            "fatal_error",
            {"error": "Resolve decision without plan result", "step_id": ""},
        )
        return {"last_outcome": "fatal"}

    decision = agent_loop._resolve_decision(plan_result, state)
    if decision is None:
        logger.error("[Reason] No executable decision after reason phase; aborting loop")
        await ctx.emit(
            "fatal_error",
            {"error": "Reason phase returned no executable plan", "step_id": ""},
        )
        return {"last_outcome": "fatal"}

    if plan_result.plan_action == "new":
        reserved = set(state.dependency_completion_ids())
        plan_id = allocate_plan_id(decision, reserved_step_ids=reserved)
        state.plan_id = plan_id
        decision = assign_plan_step_ids(decision, plan_id=plan_id)
    elif plan_result.plan_action == "keep" and state.current_decision is None:
        reserved = set(state.dependency_completion_ids())
        plan_id = state.plan_id or allocate_plan_id(decision, reserved_step_ids=reserved)
        state.plan_id = plan_id
        decision = assign_plan_step_ids(decision, plan_id=plan_id)

    if plan_result.plan_action == "new":
        state.completed_step_ids.clear()
        state.current_decision = decision

    ctx.scratch.decision = decision

    await ctx.emit(
        "plan_decision",
        {
            "iteration": state.iteration,
            "steps": [
                {"id": s.id, "description": preview_first(s.description, 80)}
                for s in decision.steps
            ],
            "execution_mode": decision.execution_mode,
        },
    )

    return {}
