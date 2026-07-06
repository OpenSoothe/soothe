"""Plan generation node (RFC-220 ``plan_generate`` after assess + pre-generate).

IG-476: Also handles fresh-loop bypass where bounded_evidence_gather sets synthetic assessment.
RFC-630: Also handles the ``simple`` intake branch (lightweight plan, synthetic assessment).
IG-555: Guardrail rejects undersized plans for complex intake at iter=0.
"""

from __future__ import annotations

import logging
from typing import Any

from soothe.foundation.sloop.cognition.plan_step_safety import (
    MAX_UNDERSIZED_PLAN_REPLANS,
    plan_has_minimum_steps_for_intake,
)
from soothe.foundation.sloop.intention.models import IntakeLabel
from soothe.foundation.sloop.state.schemas import StatusAssessment
from soothe.foundation.sloop.utils.loop_reason_display import is_displayable_plan_reasoning

from ..runtime_context import LoopRuntimeContext
from ..state import PLAN_ROUTE_EXECUTE, PLAN_ROUTE_GOAL_DONE, PlanRoute

logger = logging.getLogger(__name__)

_PLAN_GENERATE_STATUS_LABEL = "Generating plan"


async def node_plan_generate(ctx: LoopRuntimeContext, _state: dict[str, Any]) -> dict[str, Any]:
    """Run generate phase from prior assess result and set route key.

    Assessment can come from:
    1. plan_assess node (normal flow)
    2. bounded_evidence_gather (fresh-loop bypass, IG-476)
    3. synthetic, when reached via the ``simple`` intake branch (RFC-630)
    """
    strange_loop = ctx.strange_loop
    state = ctx.loop_state
    plan_manager = ctx.plan_manager
    assessment = ctx.scratch.plan_assessment
    if assessment is None:
        await ctx.emit(
            "fatal_error",
            {"error": "plan_generate invoked without prior assessment", "step_id": ""},
        )
        return {"last_outcome": "fatal"}

    # IG-476: Log when using fresh-loop bypass assessment
    if assessment.assessment_reasoning and "Fresh-loop bypass" in assessment.assessment_reasoning:
        logger.info("[PlanGenerate] Using fresh-loop bypass assessment")

    context = strange_loop._build_plan_context(state)
    exclude_goal_id = ctx.goal_record.goal_id if ctx.goal_record else None

    await ctx.emit("plan_phase_status", {"label": _PLAN_GENERATE_STATUS_LABEL})

    # RFC-630: the ``simple`` intake branch skips plan_assess and reaches
    # plan_generate directly with a synthetic assessment. Use the cheaper
    # lightweight plan call (reduced context, same schema).
    intake_label = getattr(state.intent, "intake_label", None) if state.intent else None
    if intake_label == IntakeLabel.SIMPLE:
        logger.info("[PlanGenerate] Using lightweight generate for simple intake branch")
        plan_result = await strange_loop.plan_phase.generate_lightweight(
            goal=state.goal,
            state=state,
            context=context,
            assessment=assessment,
            plan_manager=plan_manager,
            context_engine=ctx.ce,
            checkpoint=ctx.checkpoint,
            exclude_goal_id=exclude_goal_id,
        )
    else:
        plan_result = await strange_loop.plan_phase.generate_from_assessment(
            goal=state.goal,
            state=state,
            context=context,
            assessment=assessment,
            plan_manager=plan_manager,
            context_engine=ctx.ce,
            checkpoint=ctx.checkpoint,
            exclude_goal_id=exclude_goal_id,
        )

    ctx.scratch.plan_result = plan_result

    # IG-555: Guardrail rejects undersized plans for complex intake at iter=0
    if intake_label == IntakeLabel.COMPLEX and state.iteration == 0:
        if not plan_has_minimum_steps_for_intake(
            plan_result.decision,
            intake_label,
            state.iteration,
            treat_missing_as_undersized=False,
        ):
            step_count = len(plan_result.decision.steps) if plan_result.decision else 0
            if ctx.scratch.undersized_plan_replan_attempts >= MAX_UNDERSIZED_PLAN_REPLANS:
                logger.error(
                    "[PlanGenerate] Undersized plan (%d step) persists after %d replans; aborting",
                    step_count,
                    ctx.scratch.undersized_plan_replan_attempts,
                )
                await ctx.emit(
                    "fatal_error",
                    {
                        "error": "Plan remained undersized for complex goal after replan attempts",
                        "step_id": "",
                    },
                )
                return {"last_outcome": "fatal"}

            logger.warning(
                "[PlanGenerate] Undersized plan (%d step) for complex intake at iter=0; "
                "forcing replan with expanded scope",
                step_count,
            )
            ctx.scratch.undersized_plan_replan_attempts += 1
            ctx.scratch.plan_assessment = StatusAssessment(
                status="continue",
                goal_progress="low",
                assessment_reasoning="Plan undersized for complex goal; expanding scope.",
                require_goal_completion=False,
            )
            ctx.scratch.plan_result = None
            return {"assess_route": "continue_generate"}

    ctx.scratch.undersized_plan_replan_attempts = 0

    plan_reasoning = (plan_result.plan_reasoning or "").strip()
    if is_displayable_plan_reasoning(plan_reasoning):
        await ctx.emit(
            "generate",
            {
                "plan_reasoning": plan_reasoning,
                "iteration": state.iteration,
            },
        )

    await ctx.emit(
        "plan",
        {
            "iteration": state.iteration,
            "status": plan_result.status,
            "progress": plan_result.goal_progress,
            "next_action": plan_result.next_action,
            "plan_action": plan_result.plan_action,
        },
    )

    plan_route: PlanRoute = PLAN_ROUTE_GOAL_DONE if plan_result.is_done() else PLAN_ROUTE_EXECUTE
    return {"plan_route": plan_route, "assess_route": None}
