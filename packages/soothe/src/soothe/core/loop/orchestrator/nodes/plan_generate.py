"""Plan generation node (RFC-220 ``plan_generate`` after assess + pre-generate)."""

from __future__ import annotations

from typing import Any

from ..runtime_context import LoopRuntimeContext
from ..state import PLAN_ROUTE_EXECUTE, PLAN_ROUTE_GOAL_DONE, PlanRoute


async def node_plan_generate(ctx: LoopRuntimeContext, _state: dict[str, Any]) -> dict[str, Any]:
    """Run generate phase from prior assess result and set route key."""
    agent_loop = ctx.agent_loop
    state = ctx.loop_state
    plan_manager = ctx.plan_manager
    assessment = ctx.scratch.plan_assessment
    if assessment is None:
        await ctx.emit(
            "fatal_error",
            {"error": "plan_generate invoked without prior assessment", "step_id": ""},
        )
        return {"last_outcome": "fatal"}

    context = agent_loop._build_plan_context(state)
    plan_result = await agent_loop.plan_phase.generate_from_assessment(
        goal=state.goal,
        state=state,
        context=context,
        assessment=assessment,
        plan_manager=plan_manager,
    )

    ctx.scratch.plan_result = plan_result
    plan_manager.ingest_plan(plan_result, state.plan_id, state.iteration)

    await ctx.emit(
        "plan",
        {
            "iteration": state.iteration,
            "status": plan_result.status,
            "progress": plan_result.goal_progress,
            "next_action": plan_result.next_action,
            "plan_reasoning": plan_result.plan_reasoning,
            "plan_action": plan_result.plan_action,
        },
    )

    plan_route: PlanRoute = PLAN_ROUTE_GOAL_DONE if plan_result.is_done() else PLAN_ROUTE_EXECUTE
    return {"plan_route": plan_route}
