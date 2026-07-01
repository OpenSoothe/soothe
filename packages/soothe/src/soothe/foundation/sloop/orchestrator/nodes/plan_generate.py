"""Plan generation node (RFC-220 ``plan_generate`` after assess + pre-generate).

IG-476: Also handles fresh-loop bypass where bounded_evidence_gather sets synthetic assessment.
RFC-630: Also handles the ``simple`` intake branch (lightweight plan, synthetic assessment).
"""

from __future__ import annotations

import logging
from typing import Any

from soothe.foundation.sloop.intention.models import IntakeLabel
from soothe.foundation.sloop.state.schemas import StatusAssessment
from soothe.foundation.sloop.utils.loop_reason_display import is_displayable_plan_reasoning

from ..runtime_context import LoopRuntimeContext
from ..state import PLAN_ROUTE_EXECUTE, PLAN_ROUTE_GOAL_DONE, PlanRoute

logger = logging.getLogger(__name__)

_PLAN_GENERATE_STATUS_LABEL = "Generating plan"


def _create_synthetic_assessment() -> StatusAssessment:
    """Create synthetic StatusAssessment when plan_assess was skipped.

    Used by the fresh-loop bypass (IG-476) and the ``simple`` intake branch
    (RFC-630), both of which reach plan_generate without a prior assess call.
    """
    return StatusAssessment(
        status="continue",
        goal_progress="none",
        assessment_reasoning="Synthetic assessment: plan_assess skipped (fresh-loop or simple branch).",
        require_goal_completion=False,
    )


async def node_plan_generate(ctx: LoopRuntimeContext, _state: dict[str, Any]) -> dict[str, Any]:
    """Run generate phase from prior assess result and set route key.

    Assessment can come from:
    1. plan_assess node (normal flow)
    2. bounded_evidence_gather (fresh-loop bypass, IG-476)
    3. synthetic, when reached via the ``simple`` intake branch (RFC-630)
    """
    strange_loop = ctx.strange_loop
    strange_loop = strange_loop  # Legacy alias
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

    await ctx.emit("plan_phase_status", {"label": _PLAN_GENERATE_STATUS_LABEL})

    # RFC-630: the ``simple`` intake branch skips plan_assess and reaches
    # plan_generate directly with a synthetic assessment. Use the cheaper
    # lightweight plan call (reduced context, same schema).
    intake_label = getattr(state.intent, "intake_label", None) if state.intent else None
    if intake_label == IntakeLabel.SIMPLE and not state.step_results:
        logger.info("[PlanGenerate] Using lightweight generate for simple intake branch")
        plan_result = await strange_loop.plan_phase.generate_lightweight(
            goal=state.goal,
            state=state,
            context=context,
            assessment=assessment,
            plan_manager=plan_manager,
            context_engine=ctx.ce,
        )
    else:
        plan_result = await strange_loop.plan_phase.generate_from_assessment(
            goal=state.goal,
            state=state,
            context=context,
            assessment=assessment,
            plan_manager=plan_manager,
            context_engine=ctx.ce,
        )

    ctx.scratch.plan_result = plan_result

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
    return {"plan_route": plan_route}
