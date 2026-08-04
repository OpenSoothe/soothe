"""Assess-only planning node (RFC-220 split plan flow).

RFC-226 / IG-676: iter=0 mid-loop goals — trivial may run ``assess_continuation``;
simple/complex skip the discriminator and route to ``plan_generate``.

IG-555: Reject terminal done at complex iter=0 before any step results (anti-anchoring).
IG-654: Complex goals may use a single CoreAgent execute step.
"""

from __future__ import annotations

import logging
import random
from typing import Any, Literal

from soothe.sloop.cognition.plan_step_safety import (
    intake_label_from_state,
    no_new_tool_evidence_recently,
    terminal_assess_may_complete,
)
from soothe.sloop.cognition.structural_keep import (
    assess_keep_block_reason,
    build_keep_plan_result,
    remaining_plan_step_count,
)
from soothe.sloop.engine.continuation_context import (
    build_continue_bootstrap_step_briefs,
    build_prior_goal_summaries,
    polish_continuation_assess_reasoning,
)
from soothe.sloop.goal_text import resolve_planning_goal
from soothe.sloop.intention.models import IntakeLabel
from soothe.sloop.orchestrator.continuation_routing import (
    bootstrap_terminal_after_execute,
    continuation_forced_plan_generate_assessment,
    has_prior_goal_context,
)
from soothe.sloop.orchestrator.mid_loop_intake import mid_loop_skip_continuation_assess
from soothe.sloop.orchestrator.runtime_context import LoopRuntimeContext
from soothe.sloop.orchestrator.state import PLAN_ROUTE_GOAL_DONE
from soothe.sloop.stages.plan.phase_status import emit_plan_phase_status
from soothe.sloop.state.schemas import (
    AgentDecision,
    LoopState,
    PlanResult,
    StatusAssessment,
    StepAction,
    derive_plan_action,
)
from soothe.sloop.utils.continue_keyword import is_continue_keyword
from soothe.sloop.utils.messages import last_ledger_ai_content

logger = logging.getLogger(__name__)

_PLAN_ASSESS_STATUS_LABEL = "Assessing progress"
_PLAN_CONTINUATION_STATUS_LABEL = "Assessing continuation"
_DEFAULT_NO_TOOL_EVIDENCE_RETRY_LIMIT = 2


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
        and has_prior_goal_context(ctx)
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

    # Mid-loop simple/complex never bootstrap: skip assess LLM and escalate to
    # plan_generate (lightweight for simple). Trivial alone runs the discriminator.
    if mid_loop_skip_continuation_assess(intake_label):
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

    await emit_plan_phase_status(ctx, label=_PLAN_CONTINUATION_STATUS_LABEL)
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


def _downgrade_rejected_terminal_assessment(assessment: StatusAssessment) -> StatusAssessment:
    """Align scratch assessment with continue_generate after a rejected terminal route."""
    updates: dict[str, object] = {"goal_progress": "medium"}
    if assessment.status == "done":
        updates["status"] = "continue"
    return assessment.model_copy(update=updates)


def _reject_ig555_premature_complete(
    state: LoopState,
    intake_label: IntakeLabel | None,
) -> bool:
    """IG-555 iter=0 complex anti-anchoring. Returns True when routing must continue_generate."""
    if state.iteration == 0 and intake_label == IntakeLabel.COMPLEX and not state.step_results:
        logger.warning(
            "[Plan] Reject terminal assess for complex intake at iter=0 "
            "(prior completion anchoring); forcing replan"
        )
        return True
    return False


async def _route_goal_completion_if_terminal(
    ctx: LoopRuntimeContext,
    *,
    assessment: StatusAssessment,
    context: Any,
) -> dict[str, Any] | None:
    """Terminal routing keyed on authoritative assess status (IG-589)."""
    if assessment.status != "done":
        return None

    strange_loop = ctx.strange_loop
    state = ctx.loop_state
    plan_manager = ctx.plan_manager
    intake_label = intake_label_from_state(state)
    force_goal_completion = False

    if _reject_ig555_premature_complete(state, intake_label):
        ctx.scratch.plan_assessment = _downgrade_rejected_terminal_assessment(assessment)
        return {"assess_route": "continue_generate"}

    if not terminal_assess_may_complete(
        state,
        assessment,
        ctx.scratch.plan_gap,
        intake_label=intake_label,
    ):
        configured_retry_limit = _DEFAULT_NO_TOOL_EVIDENCE_RETRY_LIMIT
        try:
            config_limit = (
                ctx.strange_loop.config.agent.loop.rules.plan_safety.no_tool_evidence_retry_limit
            )
            if isinstance(config_limit, int) and config_limit >= 1:
                configured_retry_limit = config_limit
        except Exception:
            configured_retry_limit = _DEFAULT_NO_TOOL_EVIDENCE_RETRY_LIMIT

        if no_new_tool_evidence_recently(
            state,
            retry_limit=configured_retry_limit,
        ):
            logger.warning(
                "[Plan] Override terminal gate after %d no-tool verification retries; "
                "routing to goal completion (status=%s progress=%s iter=%d)",
                configured_retry_limit,
                assessment.status,
                assessment.goal_progress,
                state.iteration,
            )
            force_goal_completion = True
        else:
            logger.warning(
                "[Plan] Reject terminal assess: structural gates failed "
                "(status=%s progress=%s iter=%d)",
                assessment.status,
                assessment.goal_progress,
                state.iteration,
            )
            ctx.scratch.plan_assessment = _downgrade_rejected_terminal_assessment(assessment)
            return {"assess_route": "continue_generate"}

    if assessment.status == "done" and state.has_remaining_steps():
        logger.warning(
            "[Plan] LLM returned status=done but %d step(s) remain; proceeding to goal completion",
            len(state.current_decision.steps) - len(state.completed_step_ids),
        )

    logger.info(
        "[Plan] terminal assess routing to goal completion (status=%s progress=%s)",
        assessment.status,
        assessment.goal_progress,
    )
    gc_mode = (
        strange_loop.config.agent.loop.goal_completion_mode
        if strange_loop.config is not None
        else "llm_only"
    )
    require_completion = plan_manager.determine_goal_completion_needs(
        llm_decision=(assessment.require_goal_completion or force_goal_completion),
        state=state,
        mode=gc_mode,
    )
    next_action = "Goal achieved successfully"
    plan_result = PlanResult(
        status=assessment.status,
        goal_progress=assessment.goal_progress,
        assessment_reasoning="",
        plan_action="keep",
        decision=None,
        next_action=next_action,
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
            "plan_action": plan_result.plan_action,
        },
    )
    return {"plan_route": PLAN_ROUTE_GOAL_DONE}


async def node_plan_assess(ctx: LoopRuntimeContext, _state: dict[str, Any]) -> dict[str, Any]:
    """Run assess phase and decide whether generation is needed."""
    strange_loop = ctx.strange_loop
    state = ctx.loop_state
    context = strange_loop._build_plan_context(state)

    continuation_result = await _handle_continuation_first_plan(
        ctx,
        context=context,
        strange_loop=strange_loop,
    )
    if continuation_result is not None:
        return continuation_result

    await emit_plan_phase_status(ctx, label=_PLAN_ASSESS_STATUS_LABEL)
    assessment = await strange_loop.plan_phase.assess_status(
        goal=resolve_planning_goal(state),
        state=state,
        context=context,
        context_engine=ctx.ce,
        plan_gap=ctx.scratch.plan_gap,
    )
    await emit_plan_phase_status(ctx, label=_PLAN_ASSESS_STATUS_LABEL)
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

    terminal_route = await _route_goal_completion_if_terminal(
        ctx,
        assessment=assessment,
        context=context,
    )
    if terminal_route is not None:
        return terminal_route

    # IG-671: reuse in-flight plan without entering generate_plan.
    # IG-683: refuse keep when the last wave failed (or stuck) — force replan.
    if (
        derive_plan_action(
            assessment_status=assessment.status,
            has_remaining_steps=state.has_remaining_steps(),
        )
        == "keep"
    ):
        keep_block = assess_keep_block_reason(state)
        if keep_block is not None:
            logger.warning(
                "[Plan] Reject assess keep: %s → continue_generate (force replan)",
                keep_block,
            )
            assessment.status = "replan"
            if assessment.goal_progress in ("medium", "high", "complete"):
                assessment.goal_progress = "low"
            prior = (assessment.assessment_reasoning or "").strip()
            forced = f"Forced replan: {keep_block}"
            assessment.assessment_reasoning = f"{prior} ({forced})" if prior else forced
            ctx.scratch.plan_assessment = assessment
            return {"assess_route": "continue_generate"}

        plan_result = build_keep_plan_result(
            state,
            status=assessment.status,
            goal_progress=assessment.goal_progress,
            require_goal_completion=assessment.require_goal_completion,
        )
        plan_result = strange_loop.plan_phase.finalize_plan_result(
            state=state,
            context=context,
            result=plan_result,
        )
        ctx.scratch.plan_result = plan_result
        plan_manager = ctx.plan_manager
        plan_manager.ingest_plan(plan_result, state.plan_id, state.iteration)
        if ctx.ce is not None:
            try:
                ctx.ce.defer_save()
            except Exception:
                logger.warning("[plan_assess] CE save failed on keep", exc_info=True)
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
        logger.info(
            "[Plan] assess keep → skip_generate (%d step(s) remain)",
            remaining_plan_step_count(state),
        )
        return {"assess_route": "skip_generate"}

    return {"assess_route": "continue_generate"}
