"""Assess-only planning node (RFC-220 split plan flow)."""

from __future__ import annotations

import logging
from typing import Any

from soothe.core.agent_loop.core.thread_continuation_bootstrap import (
    build_thread_continuation_bootstrap_plan,
    thread_continuation_plan_bootstrap_allowed,
)
from soothe.core.agent_loop.policies.goal_completion_policy import (
    determine_goal_completion_needs,
)
from soothe.core.agent_loop.state.schemas import PlanResult

from ..runtime_context import LoopRuntimeContext
from ..state import PLAN_ROUTE_GOAL_DONE

logger = logging.getLogger(__name__)


async def node_plan_assess(ctx: LoopRuntimeContext, _state: dict[str, Any]) -> dict[str, Any]:
    """Run assess phase and decide whether generation is needed."""
    agent_loop = ctx.agent_loop
    state = ctx.loop_state
    context = agent_loop._build_plan_context(state)

    # Backward compatibility for tests/integrations that monkeypatch PlanPhase.plan directly.
    one_shot_plan = agent_loop.plan_phase.plan
    if getattr(one_shot_plan, "__self__", None) is None:
        plan_result = await one_shot_plan(goal=state.goal, state=state, context=context)
        plan_result = agent_loop.plan_phase.finalize_plan_result(
            state=state,
            context=context,
            result=plan_result,
        )
        ctx.scratch.plan_result = plan_result
        await ctx.emit(
            "plan",
            {
                "iteration": state.iteration,
                "status": plan_result.status,
                "progress": plan_result.goal_progress,
                "next_action": plan_result.next_action,
                "assessment_reasoning": plan_result.assessment_reasoning,
                "plan_reasoning": plan_result.plan_reasoning,
                "plan_action": plan_result.plan_action,
            },
        )
        if plan_result.is_done():
            return {"plan_route": PLAN_ROUTE_GOAL_DONE}
        return {"assess_route": "skip_generate"}

    if thread_continuation_plan_bootstrap_allowed(
        thread_continuation_mode=ctx.thread_continuation_mode,
        state=state,
        recovery_valid_resume=ctx.recovery_valid_resume,
        goal_record=ctx.goal_record,
    ):
        logger.info("[Plan] iter=0 thread_continuation bootstrap (no planner LLM)")
        plan_result = build_thread_continuation_bootstrap_plan(state.goal)
        ctx.scratch.plan_result = plan_result
        ctx.scratch.plan_assessment = None
        await ctx.emit(
            "plan",
            {
                "iteration": state.iteration,
                "status": plan_result.status,
                "progress": plan_result.goal_progress,
                "next_action": plan_result.next_action,
                "assessment_reasoning": plan_result.assessment_reasoning,
                "plan_reasoning": plan_result.plan_reasoning,
                "plan_action": plan_result.plan_action,
            },
        )
        return {"assess_route": "skip_generate"}

    assessment = await agent_loop.plan_phase.assess_status(
        goal=state.goal,
        state=state,
        context=context,
    )
    ctx.scratch.plan_assessment = assessment

    if assessment.status == "done":
        gc_mode = (
            agent_loop.config.agentic.goal_completion_mode
            if agent_loop.config is not None
            else "llm_only"
        )
        require_completion = determine_goal_completion_needs(
            llm_decision=assessment.require_goal_completion,
            state=state,
            mode=gc_mode,
        )
        plan_result = PlanResult(
            status=assessment.status,
            goal_progress=assessment.goal_progress,
            assessment_reasoning="",
            plan_reasoning="",
            plan_action="keep",
            decision=None,
            next_action="Goal achieved successfully",
            require_goal_completion=require_completion,
            full_output=state.last_execute_assistant_text,
        )
        plan_result = agent_loop.plan_phase.finalize_plan_result(
            state=state,
            context=context,
            result=plan_result,
        )
        ctx.scratch.plan_result = plan_result
        await ctx.emit(
            "plan",
            {
                "iteration": state.iteration,
                "status": plan_result.status,
                "progress": plan_result.goal_progress,
                "next_action": plan_result.next_action,
                "assessment_reasoning": plan_result.assessment_reasoning,
                "plan_reasoning": plan_result.plan_reasoning,
                "plan_action": plan_result.plan_action,
            },
        )
        return {"plan_route": PLAN_ROUTE_GOAL_DONE}

    return {"assess_route": "continue_generate"}
