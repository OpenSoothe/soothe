"""Assess-only planning node (RFC-220 split plan flow).

RFC-226: iter=0 continuation goals coordinate intake complexity with optional
``assess_continuation`` for trivial follow-ups. Simple/complex intake skips the
discriminator and routes to ``plan_generate`` (or the evidence-gather spine).

IG-555: Structural guardrail rejects undersized plans for complex intake at iter=0.
"""

from __future__ import annotations

import logging
import random
from typing import Any, Literal

from soothe.foundation.sloop.cognition.plan_step_safety import (
    assess_may_route_complete,
    assess_respects_gap_analysis,
    intake_label_from_state,
    plan_has_minimum_steps_for_intake,
)
from soothe.foundation.sloop.engine.continuation_context import (
    build_continue_bootstrap_step_briefs,
    build_prior_goal_summaries,
    polish_continuation_assess_reasoning,
)
from soothe.foundation.sloop.goal_text import resolve_planning_goal
from soothe.foundation.sloop.intention.models import IntakeLabel
from soothe.foundation.sloop.orchestrator.continuation_routing import (
    bootstrap_terminal_after_execute,
    continuation_forced_plan_generate_assessment,
)
from soothe.foundation.sloop.state.schemas import (
    AgentDecision,
    LoopState,
    PlanResult,
    StatusAssessment,
    StepAction,
)
from soothe.foundation.sloop.utils.continue_keyword import is_continue_keyword
from soothe.foundation.sloop.utils.messages import last_ledger_ai_content

from ..runtime_context import LoopRuntimeContext
from ..state import PLAN_ROUTE_GOAL_DONE

logger = logging.getLogger(__name__)

_PLAN_ASSESS_STATUS_LABEL = "Assessing goal progress"
_PLAN_CONTINUATION_STATUS_LABEL = "Assessing continuation context"


async def _emit_plan_phase_status(
    ctx: LoopRuntimeContext,
    *,
    label: str,
) -> None:
    """Update TUI spinner/status while plan assess or generate LLM calls run."""
    await ctx.emit("plan_phase_status", {"label": label})


# Ordered progress buckets shared by the digest hint and StatusAssessment.goal_progress.
# Used by `_log_prior_progress_disagreement` to compare across the two signals.
_PROGRESS_BUCKETS: tuple[str, ...] = ("none", "low", "medium", "high", "complete")


def _log_prior_progress_disagreement(state: LoopState, assessment: StatusAssessment) -> None:
    """Emit an INFO log when the per-wave digest hint and the LLM disagree.

    Disagreement is defined as the two values being more than one bucket apart
    on the ordered ``_PROGRESS_BUCKETS`` scale. Telemetry only — never overrides
    the assessment.
    """
    digest = state.prior_progress
    if digest is None:
        return
    try:
        hint_idx = _PROGRESS_BUCKETS.index(digest.derived_progress_hint)
        llm_idx = _PROGRESS_BUCKETS.index(assessment.goal_progress)
    except ValueError:
        return
    if abs(hint_idx - llm_idx) > 1:
        logger.info(
            "[Plan] prior_progress hint=%s vs LLM goal_progress=%s (iter=%d)",
            digest.derived_progress_hint,
            assessment.goal_progress,
            state.iteration,
        )


# First-person action descriptions for continue-thread bootstrap (< 15 words each)
_CONTINUE_THREAD_DESCRIPTIONS = [
    "I'll address your follow-up using our conversation context.",
    "I'll continue from where we left off to help you.",
    "I'll respond to your request using prior context.",
    "I'll handle this follow-up based on our earlier work.",
    "I'll proceed with your request from our previous context.",
]


def _has_prior_goal_for_continuation(ctx: LoopRuntimeContext) -> bool:
    """Check CE DAG for prior goal work usable by continuation routing."""
    if ctx.ce is None:
        return False
    current_id = ctx.ce_goal_id
    for goal in ctx.ce.get_all_goals():
        if current_id and goal.id == current_id:
            continue
        completed_steps = [s for s in goal.steps.nodes.values() if s.status == "completed"]
        if completed_steps or goal.action_history:
            return True
        if goal.status in ("completed", "cancelled", "failed"):
            return True
    if ctx.checkpoint and len(ctx.checkpoint.goal_history) >= 2:
        return True
    return False


def build_continue_loop_bootstrap_plan(
    goal: str,
    *,
    raw_user_goal: str | None = None,
    terminal_after_execute: bool | None = None,
    multi_phase: bool | None = None,
    reasoning: str = "",
    goal_progress: Literal["none", "low", "medium", "high", "complete"] = "low",
) -> PlanResult:
    """Build a synthetic first ``PlanResult`` for loop continuation (RFC-225, RFC-226).

    The executor grounds prior work via projected ``goal_completion`` ledger rows
    (execute Slice A), not by replaying prior execute-step ledger rows.

    Args:
        goal: Resolved continuation goal text (often same as ``raw_user_goal``).
        raw_user_goal: Original user submission (e.g. lone ``continue`` keyword).
        terminal_after_execute: When True (RFC-226), the plan asserts its single
            step IS the goal completion; ``record_iteration`` routes directly to
            ``goal_completion`` without an iter=1 status check. When None, derived
            from goal text and Pass 2 ``multi_phase``.
        reasoning: One-sentence assessment reasoning from the discriminator LLM.
        goal_progress: Initial progress estimate.

    Returns:
        ``PlanResult`` with ``status=continue`` and a single parallel step.
    """
    user_goal = (raw_user_goal or goal).strip()
    next_action = random.choice(_CONTINUE_THREAD_DESCRIPTIONS)
    briefs = build_continue_bootstrap_step_briefs(user_goal=user_goal)
    if terminal_after_execute is None:
        terminal_after_execute = bootstrap_terminal_after_execute(
            raw_user_goal=user_goal,
            multi_phase=multi_phase,
        )
    default_reasoning = (
        ""
        if is_continue_keyword(user_goal)
        else "Loop-continuation bootstrap: initial planner call skipped."
    )
    decision = AgentDecision(
        type="execute_steps",
        steps=[
            StepAction(
                description=briefs.description,
                full_description=briefs.full_description,
                expected_output=(
                    "Concrete progress on the recommended next actions from the prior goal "
                    "completion report, without repeating prior goal discovery or analysis."
                ),
            )
        ],
        execution_mode="parallel",
        reasoning="Loop-continuation first-plan bootstrap (no planner LLM).",
    )
    return PlanResult(
        status="continue",
        goal_progress=goal_progress,
        assessment_reasoning=reasoning or default_reasoning,
        plan_reasoning="Single execute wave grounded on prior goal completion report.",
        next_action=next_action,
        plan_action="new",
        decision=decision,
        require_goal_completion=False,
        terminal_after_execute=terminal_after_execute,
    )


async def _emit_continuation_bootstrap_plan(
    ctx: LoopRuntimeContext,
    *,
    plan_result: PlanResult,
) -> None:
    """Emit plan wire event for continuation bootstrap."""
    state = ctx.loop_state
    if is_continue_keyword(state.goal):
        await ctx.emit(
            "plan",
            {
                "iteration": state.iteration,
                "status": plan_result.status,
                "progress": plan_result.goal_progress,
                "next_action": "",
                "assessment_reasoning": "",
                "plan_reasoning": "",
                "plan_action": plan_result.plan_action,
            },
        )
    else:
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


async def _handle_continuation_first_plan(
    ctx: LoopRuntimeContext,
    *,
    context: Any,
    strange_loop: Any,
) -> dict[str, Any] | None:
    """Run iter=0 continuation routing when eligible; None to fall through."""
    state = ctx.loop_state
    if not (
        state.iteration == 0
        and ctx.continue_loop_mode
        and not state.step_results
        and _has_prior_goal_for_continuation(ctx)
        and (
            not ctx.recovery_valid_resume
            or (
                ctx.goal_record is not None
                and ctx.ce is not None
                and len(ctx.ce.ledger.get_messages()) == 0
            )
        )
    ):
        return None

    prior_goals = build_prior_goal_summaries(
        ce=ctx.ce,
        checkpoint=ctx.checkpoint,
        exclude_goal_id=ctx.goal_record.goal_id if ctx.goal_record else None,
    )
    if not prior_goals:
        return None

    intake_label = intake_label_from_state(state)

    if intake_label in (IntakeLabel.SIMPLE, IntakeLabel.COMPLEX):
        logger.info("[Plan] continuation-assess skipped (intake=%s)", intake_label.value)
        ctx.scratch.plan_assessment = continuation_forced_plan_generate_assessment()
        return {"assess_route": "continue_generate"}

    multi_phase = getattr(state.intent, "multi_phase", None) if state.intent else None
    if multi_phase:
        logger.info("[Plan] continuation guardrail: multi-step goal forced plan_generate")
        ctx.scratch.plan_assessment = continuation_forced_plan_generate_assessment()
        return {"assess_route": "continue_generate"}

    if is_continue_keyword(state.goal):
        logger.info("[Plan] iter=0 continuation-assess: bootstrap (continue keyword)")
        plan_result = build_continue_loop_bootstrap_plan(
            state.goal,
            raw_user_goal=state.goal,
            terminal_after_execute=True,
            reasoning="",
            goal_progress="low",
        )
        ctx.scratch.plan_result = plan_result
        ctx.scratch.plan_assessment = None
        await _emit_continuation_bootstrap_plan(ctx, plan_result=plan_result)
        return {"assess_route": "skip_generate"}

    await _emit_plan_phase_status(ctx, label=_PLAN_CONTINUATION_STATUS_LABEL)
    context_bundle = None
    if ctx.ce is not None:
        try:
            context_bundle = await ctx.ce.project(goal_id=ctx.ce_goal_id)
        except Exception:
            logger.debug(
                "[Plan] continuation-assess: ContextEngine.project() failed",
                exc_info=True,
            )
    assessment = await strange_loop.loop_planner.assess_continuation(
        state=state,
        context=context,
        checkpoint=ctx.checkpoint,
        exclude_goal_id=ctx.goal_record.goal_id if ctx.goal_record else None,
        context_bundle=context_bundle,
    )
    reason_text = polish_continuation_assess_reasoning(assessment.reasoning or "")
    if assessment.action == "bootstrap":
        logger.info(
            "[Plan] iter=0 continuation-assess: bootstrap (%s)",
            reason_text[:120],
        )
        plan_result = build_continue_loop_bootstrap_plan(
            state.goal,
            raw_user_goal=state.goal,
            terminal_after_execute=None,
            multi_phase=getattr(state.intent, "multi_phase", None) if state.intent else None,
            reasoning=reason_text,
            goal_progress=assessment.goal_progress,
        )
        ctx.scratch.plan_result = plan_result
        ctx.scratch.plan_assessment = None
        await _emit_continuation_bootstrap_plan(ctx, plan_result=plan_result)
        return {"assess_route": "skip_generate"}

    if reason_text:
        await ctx.emit(
            "assess",
            {
                "assessment_reasoning": reason_text,
                "iteration": state.iteration,
            },
        )
    logger.info(
        "[Plan] iter=0 continuation-assess: plan_generate (%s)",
        reason_text[:120],
    )
    ctx.scratch.plan_assessment = StatusAssessment(
        status="continue",
        goal_progress=assessment.goal_progress,
        assessment_reasoning=reason_text,
        require_goal_completion=False,
    )
    return {"assess_route": "continue_generate"}


async def node_plan_assess(ctx: LoopRuntimeContext, _state: dict[str, Any]) -> dict[str, Any]:
    """Run assess phase and decide whether generation is needed."""
    strange_loop = ctx.strange_loop
    state = ctx.loop_state
    plan_manager = ctx.plan_manager
    context = strange_loop._build_plan_context(state)

    continuation_result = await _handle_continuation_first_plan(
        ctx,
        context=context,
        strange_loop=strange_loop,
    )
    if continuation_result is not None:
        return continuation_result

    await _emit_plan_phase_status(ctx, label=_PLAN_ASSESS_STATUS_LABEL)
    assessment = await strange_loop.plan_phase.assess_status(
        goal=resolve_planning_goal(state),
        state=state,
        context=context,
        context_engine=ctx.ce,
        plan_gap=ctx.scratch.plan_gap,
    )
    ctx.scratch.plan_assessment = assessment

    _log_prior_progress_disagreement(state, assessment)

    if assessment.assessment_reasoning:
        await ctx.emit(
            "assess",
            {
                "assessment_reasoning": assessment.assessment_reasoning,
                "iteration": state.iteration,
            },
        )

    if assessment.status == "done":
        if state.has_remaining_steps():
            logger.warning(
                "[Plan] LLM returned status=done but %d step(s) remain; proceeding to goal completion (no new plan will be generated)",
                len(state.current_decision.steps) - len(state.completed_step_ids),
            )

        gc_mode = (
            strange_loop.config.agent.loop.goal_completion_mode
            if strange_loop.config is not None
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
            full_output=last_ledger_ai_content(state) or None,
        )
        plan_result = strange_loop.plan_phase.finalize_plan_result(
            state=state,
            context=context,
            result=plan_result,
        )
        ctx.scratch.plan_result = plan_result
        plan_manager.ingest_plan(plan_result, state.plan_id, state.iteration)
        # RFC-624 Phase 4: persist CE state after plan ingestion
        if ctx.ce is not None:
            try:
                ctx.ce.defer_save()
            except Exception:
                logger.warning("[plan_assess] CE save failed", exc_info=True)
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
        return {"plan_route": PLAN_ROUTE_GOAL_DONE}

    # goal_progress-based early routing: when progress is complete, go to goal completion
    # IG-555: Guardrail rejects premature "complete" for complex intake at iter=0
    if assessment.goal_progress == "complete":
        intake_label = intake_label_from_state(state)
        if state.iteration == 0 and intake_label == IntakeLabel.COMPLEX and not state.step_results:
            logger.warning(
                "[Plan] Reject goal_progress=complete for complex intake at iter=0 "
                "(prior completion anchoring); forcing replan"
            )
            assessment.goal_progress = "medium"
            return {"assess_route": "continue_generate"}

        # Check undersized plan for complex intake (IG-555)
        if not plan_has_minimum_steps_for_intake(
            state.current_decision,
            intake_label,
            state.iteration,
        ):
            logger.warning(
                "[Plan] Reject goal_progress=complete: undersized plan (%d step) "
                "for complex intake at iter=0, forcing replan",
                len(state.current_decision.steps) if state.current_decision else 0,
            )
            assessment.goal_progress = "medium"
            return {"assess_route": "continue_generate"}

        if not assess_may_route_complete(state, assessment, intake_label):
            logger.warning(
                "[Plan] Reject goal_progress=complete: insufficient execution evidence (iter=%d)",
                state.iteration,
            )
            assessment.goal_progress = "medium"
            return {"assess_route": "continue_generate"}

        if not assess_respects_gap_analysis(assessment, ctx.scratch.plan_gap):
            gap = ctx.scratch.plan_gap
            logger.warning(
                "[Plan] Reject assessment: contradicts gap analysis (distance=%s)",
                gap.distance_from_goal if gap is not None else "n/a",
            )
            assessment.goal_progress = "medium"
            return {"assess_route": "continue_generate"}

        logger.info(
            "[Plan] goal_progress=%s routing to goal completion",
            assessment.goal_progress,
        )
        gc_mode = (
            strange_loop.config.agent.loop.goal_completion_mode
            if strange_loop.config is not None
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
            next_action="Goal progress sufficient for completion",
            require_goal_completion=require_completion,
        )
        plan_result = strange_loop.plan_phase.finalize_plan_result(
            state=state,
            context=context,
            result=plan_result,
        )
        ctx.scratch.plan_result = plan_result
        plan_manager.ingest_plan(plan_result, state.plan_id, state.iteration)
        # RFC-624 Phase 4: persist CE state after plan ingestion
        if ctx.ce is not None:
            try:
                ctx.ce.defer_save()
            except Exception:
                logger.warning("[plan_assess] CE save failed", exc_info=True)
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
        return {"plan_route": PLAN_ROUTE_GOAL_DONE}

    return {"assess_route": "continue_generate"}
