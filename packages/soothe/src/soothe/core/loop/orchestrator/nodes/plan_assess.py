"""Assess-only planning node (RFC-220 split plan flow)."""

from __future__ import annotations

import logging
from typing import Any

from soothe.core.loop.engine.continue_thread import (
    build_continue_thread_bootstrap_plan,
    continue_thread_plan_bootstrap_allowed,
)
from soothe.core.loop.state.schemas import PlanResult

from ..runtime_context import LoopRuntimeContext
from ..state import PLAN_ROUTE_GOAL_DONE

logger = logging.getLogger(__name__)


async def node_plan_assess(ctx: LoopRuntimeContext, _state: dict[str, Any]) -> dict[str, Any]:
    """Run assess phase and decide whether generation is needed."""
    agent_loop = ctx.agent_loop
    state = ctx.loop_state
    plan_manager = ctx.plan_manager
    context = agent_loop._build_plan_context(state)

    if continue_thread_plan_bootstrap_allowed(
        continue_thread_mode=ctx.continue_thread_mode,
        state=state,
        recovery_valid_resume=ctx.recovery_valid_resume,
        goal_record=ctx.goal_record,
    ):
        logger.info("[Plan] iter=0 continue-thread bootstrap (no planner LLM)")
        plan_result = build_continue_thread_bootstrap_plan(state.goal)
        ctx.scratch.plan_result = plan_result
        ctx.scratch.plan_assessment = None
        plan_manager.ingest_plan(plan_result, state.plan_id, state.iteration)
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
        if state.has_remaining_steps():
            logger.warning(
                "[Plan] LLM returned status=done but %d step(s) remain; proceeding to goal completion (no new plan will be generated)",
                len(state.current_decision.steps) - len(state.completed_step_ids),
            )

        gc_mode = (
            agent_loop.config.agent_loop.goal_completion_mode
            if agent_loop.config is not None
            else "llm_only"
        )
        require_completion = plan_manager.determine_goal_completion_needs(
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
        plan_manager.ingest_plan(plan_result, state.plan_id, state.iteration)
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

    # goal_progress-based early routing: when progress is complete, go to goal completion
    if assessment.goal_progress == "complete":
        logger.info(
            "[Plan] goal_progress=%s routing to goal completion",
            assessment.goal_progress,
        )
        gc_mode = (
            agent_loop.config.agent_loop.goal_completion_mode
            if agent_loop.config is not None
            else "llm_only"
        )
        require_completion = plan_manager.determine_goal_completion_needs(
            llm_decision=assessment.require_goal_completion,
            state=state,
            mode=gc_mode,
        )
        plan_result = PlanResult(
            status=assessment.status,
            goal_progress=assessment.goal_progress,
            assessment_reasoning=assessment.assessment_reasoning or "",
            plan_reasoning="",
            plan_action="keep",
            decision=None,
            next_action="Goal progress sufficient for completion",
            require_goal_completion=require_completion,
        )
        plan_result = agent_loop.plan_phase.finalize_plan_result(
            state=state,
            context=context,
            result=plan_result,
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
                "assessment_reasoning": plan_result.assessment_reasoning,
                "plan_reasoning": plan_result.plan_reasoning,
                "plan_action": plan_result.plan_action,
            },
        )
        return {"plan_route": PLAN_ROUTE_GOAL_DONE}

    return {"assess_route": "continue_generate"}
