"""Plan generation (RFC-220 ``plan_generate``).

Combines RFC-604 assessment + plan generation in one planner round-trip via ``PlanPhase``
(RFC-604 ``LoopPlannerProtocol``). Normative separate ``assess`` LLM node requires planner split.
"""

from __future__ import annotations

import logging
from typing import Any

from soothe.core.agent_loop.core.thread_continuation_bootstrap import (
    build_thread_continuation_bootstrap_plan,
    thread_continuation_plan_bootstrap_allowed,
)

from ..runtime_context import LoopRuntimeContext
from ..state import PLAN_ROUTE_EXECUTE, PLAN_ROUTE_GOAL_DONE, PlanRoute

logger = logging.getLogger(__name__)


async def node_plan_generate(ctx: LoopRuntimeContext, _state: dict[str, Any]) -> dict[str, Any]:
    """Run plan phase; stash ``PlanResult`` on scratch and set routing key for LangGraph edges."""
    agent_loop = ctx.agent_loop
    state = ctx.loop_state

    if thread_continuation_plan_bootstrap_allowed(
        thread_continuation_mode=ctx.thread_continuation_mode,
        state=state,
        recovery_valid_resume=ctx.recovery_valid_resume,
        goal_record=ctx.goal_record,
    ):
        logger.info("[Plan] iter=0 thread_continuation bootstrap (no planner LLM)")
        plan_result = build_thread_continuation_bootstrap_plan(state.goal)
    else:
        plan_result = await agent_loop.plan_phase.plan(
            goal=state.goal,
            state=state,
            context=agent_loop._build_plan_context(state),
        )

    ctx.scratch.plan_result = plan_result

    await ctx.emit(
        "plan",
        {
            "iteration": state.iteration,
            "status": plan_result.status,
            "progress": plan_result.goal_progress,
            "confidence": plan_result.confidence,
            "next_action": plan_result.next_action,
            "assessment_reasoning": plan_result.assessment_reasoning,
            "plan_reasoning": plan_result.plan_reasoning,
            "plan_action": plan_result.plan_action,
        },
    )

    plan_route: PlanRoute = PLAN_ROUTE_GOAL_DONE if plan_result.is_done() else PLAN_ROUTE_EXECUTE
    return {"plan_route": plan_route}
