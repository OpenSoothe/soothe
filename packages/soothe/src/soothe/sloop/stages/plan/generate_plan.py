"""Plan generation node (RFC-220 ``plan_generate`` after assess + pre-generate).

Also handles fresh-loop bypass where bounded_evidence_gather sets synthetic assessment.
RFC-630: Also handles the ``simple`` intake branch (lightweight plan, synthetic assessment).
Complex goals may use a single CoreAgent execute step.
"""

from __future__ import annotations

import logging
from typing import Any

from soothe.sloop.orchestrator.continuation import (
    FRESH_LOOP_BYPASS_PREFIX,
    mid_loop_use_lightweight_generate,
)
from soothe.sloop.orchestrator.runtime_context import LoopRuntimeContext
from soothe.sloop.orchestrator.stations import PLAN_ROUTE_EXECUTE, PLAN_ROUTE_GOAL_DONE, PlanRoute
from soothe.sloop.stages.plan._helpers import resolve_loop_planner
from soothe.sloop.stages.plan.phase_status import emit_plan_phase_status
from soothe.sloop.utils.goal_text import resolve_planning_goal

logger = logging.getLogger(__name__)

_PLAN_GENERATE_STATUS_LABEL = "Generating plan"
_PLAN_GENERATE_FATAL: dict[str, Any] = {"last_outcome": "fatal", "assess_route": None}


async def node_plan_generate(ctx: LoopRuntimeContext, _state: dict[str, Any]) -> dict[str, Any]:
    """Run generate phase from prior assess result and set route key.

    Assessment can come from:
    1. plan_assess node (normal flow)
    2. bounded_evidence_gather (fresh-loop bypass)
    3. synthetic, when reached via the ``simple`` intake branch (RFC-630)
    4. synthetic, when Approve hands off from the planner subagent

    Langfuse: parent ``generate-plan`` span; planner LLM pinned to the goal-loop
    trace for the duration of this station (including lightweight generate).
    """
    strange_loop = ctx.strange_loop
    state = ctx.loop_state
    logger.info(
        "[PlanGenerate] start loop_id=%s iteration=%s",
        ctx.state_manager.loop_id,
        state.iteration,
    )
    plan_manager = ctx.plan_manager
    assessment = ctx.scratch.plan_assessment
    if assessment is None:
        await ctx.emit(
            "fatal_error",
            {"error": "plan_generate invoked without prior assessment", "step_id": ""},
        )
        return _PLAN_GENERATE_FATAL

    # hydrate approved-plan grounding from scratch when handoff is active.
    if getattr(ctx.scratch, "planner_implement_handoff", False):
        if not (getattr(state, "approved_plan_markdown", None) or "").strip():
            from soothe.sloop.plans.artifact import strip_plan_frontmatter

            raw = getattr(ctx.scratch, "plan_artifact_markdown", None) or ""
            body = strip_plan_frontmatter(raw)
            if body:
                state.approved_plan_markdown = body
                state.approved_plan_path = getattr(ctx.scratch, "plan_artifact_path", None)
        logger.info("[PlanGenerate] Implementing operator-approved plan artifact")

    # Log when using fresh-loop bypass assessment
    if assessment.assessment_reasoning and assessment.assessment_reasoning.startswith(
        FRESH_LOOP_BYPASS_PREFIX
    ):
        logger.info("[PlanGenerate] Using fresh-loop bypass assessment")

    context = strange_loop._build_plan_context(state)
    exclude_goal_id = ctx.goal_record.goal_id if ctx.goal_record else None

    await emit_plan_phase_status(ctx, label=_PLAN_GENERATE_STATUS_LABEL)

    from soothe.utils.observability.langfuse import (
        bind_planner_langfuse_trace,
        generate_plan_langfuse_span_async,
        restore_planner_langfuse_trace,
    )

    config = getattr(strange_loop, "config", None)
    planner = resolve_loop_planner(ctx)
    prior_pin = bind_planner_langfuse_trace(planner, ctx.goal_trace)

    # RFC-630 / simple intake uses the cheaper lightweight plan call.
    intake_label = getattr(state.intent, "intake_label", None) if state.intent else None
    lightweight = mid_loop_use_lightweight_generate(intake_label)

    try:
        async with generate_plan_langfuse_span_async(
            soothe_config=config,
            goal_trace=ctx.goal_trace,
            metadata={
                "iteration": state.iteration,
                "thread_id": state.thread_id,
                "lightweight": lightweight,
            },
        ) as span:
            if lightweight:
                logger.info("[PlanGenerate] Using lightweight generate for simple intake branch")
                plan_result = await strange_loop.plan_phase.generate_lightweight(
                    goal=resolve_planning_goal(state),
                    state=state,
                    context=context,
                    assessment=assessment,
                    plan_manager=plan_manager,
                    context_engine=ctx.ce,
                    checkpoint=ctx.checkpoint,
                    exclude_goal_id=exclude_goal_id,
                    plan_gap=ctx.scratch.plan_gap,
                )
            else:
                plan_result = await strange_loop.plan_phase.generate_from_assessment(
                    goal=resolve_planning_goal(state),
                    state=state,
                    context=context,
                    assessment=assessment,
                    plan_manager=plan_manager,
                    context_engine=ctx.ce,
                    checkpoint=ctx.checkpoint,
                    exclude_goal_id=exclude_goal_id,
                    plan_gap=ctx.scratch.plan_gap,
                )

            if span is not None:
                try:
                    step_n = (
                        len(plan_result.decision.steps) if plan_result.decision is not None else 0
                    )
                    span.update(
                        output={
                            "status": plan_result.status,
                            "plan_action": plan_result.plan_action,
                            "steps": step_n,
                            "lightweight": lightweight,
                        }
                    )
                except Exception:
                    logger.debug("[Plan] generate-plan Langfuse span.update failed", exc_info=True)
    finally:
        restore_planner_langfuse_trace(planner, prior_pin)

    await emit_plan_phase_status(ctx, label=_PLAN_GENERATE_STATUS_LABEL)

    ctx.scratch.plan_result = plan_result

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

    # one-shot handoff — stop injecting APPROVED PLAN on later waves.
    ctx.scratch.planner_implement_handoff = False
    state.approved_plan_markdown = None
    state.approved_plan_path = None

    plan_route: PlanRoute = PLAN_ROUTE_GOAL_DONE if plan_result.is_done() else PLAN_ROUTE_EXECUTE
    step_n = len(plan_result.decision.steps) if plan_result.decision is not None else 0
    logger.info(
        "[PlanGenerate] complete loop_id=%s iteration=%s plan_route=%s steps=%d",
        ctx.state_manager.loop_id,
        state.iteration,
        plan_route,
        step_n,
    )
    return {
        "plan_route": plan_route,
        "assess_route": None,
        "planner_implement_handoff": False,
    }
