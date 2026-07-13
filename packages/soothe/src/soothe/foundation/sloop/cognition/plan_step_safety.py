"""Plan step safety helpers for simple-intake goals (post-search blow-up guard)."""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING

from soothe.config.models import PlanSafetyRulesConfig
from soothe.foundation.sloop.intention.models import IntakeLabel
from soothe.foundation.sloop.state.schemas import (
    AgentDecision,
    GoalComponentStatus,
    PlanGapAnalysis,
    StatusAssessment,
    StepAction,
)

if TYPE_CHECKING:
    from soothe.foundation.sloop.state.schemas import LoopState

# IG-555: max plan_generate retries when complex iter=0 plans stay undersized.
MAX_UNDERSIZED_PLAN_REPLANS = 2

_DEFAULT_PLAN_SAFETY_RULES = PlanSafetyRulesConfig()
_PROGRESS_BUCKETS: tuple[str, ...] = ("none", "low", "medium", "high", "complete")
_MIN_GOAL_PROGRESS_FOR_DONE = "medium"
_DIGEST_DISAGREEMENT_BUCKET_THRESHOLD = 1
logger = logging.getLogger(__name__)
_FILLER_STEP_RES = tuple(
    re.compile(pattern, re.IGNORECASE)
    for pattern in _DEFAULT_PLAN_SAFETY_RULES.banned_step_patterns
)

_SIMPLE_EVIDENCE_MIN_CHARS = _DEFAULT_PLAN_SAFETY_RULES.simple_evidence_min_chars


def _filler_patterns(plan_rules: PlanSafetyRulesConfig | None) -> tuple[re.Pattern[str], ...]:
    rules = plan_rules or _DEFAULT_PLAN_SAFETY_RULES
    if rules is _DEFAULT_PLAN_SAFETY_RULES:
        return _FILLER_STEP_RES
    return tuple(re.compile(pattern, re.IGNORECASE) for pattern in rules.banned_step_patterns)


def intake_label_from_state(state: LoopState) -> IntakeLabel | None:
    """Return the intake label stored on ``state.intent``, if any."""
    intent = state.intent
    if intent is None:
        return None
    label = getattr(intent, "intake_label", None)
    if isinstance(label, IntakeLabel):
        return label
    if isinstance(label, str):
        try:
            return IntakeLabel(label)
        except ValueError:
            return None
    return None


def plan_has_minimum_steps_for_intake(
    decision: AgentDecision | None,
    intake_label: IntakeLabel | None,
    iteration: int,
    *,
    treat_missing_as_undersized: bool = True,
) -> bool:
    """Return True when a plan satisfies the complex-intake minimum step count (IG-555)."""
    if intake_label != IntakeLabel.COMPLEX:
        return True
    if iteration > 0:
        return True
    if decision is None:
        return not treat_missing_as_undersized
    steps = getattr(decision, "steps", None)
    if not steps:
        return not treat_missing_as_undersized
    return len(steps) >= 2


def simple_intake_should_force_done(
    state: LoopState,
    assessment: StatusAssessment,
    *,
    plan_rules: PlanSafetyRulesConfig | None = None,
) -> bool:
    """True when a ``simple`` goal has enough evidence to skip another plan wave."""
    rules = plan_rules or _DEFAULT_PLAN_SAFETY_RULES
    if intake_label_from_state(state) != IntakeLabel.SIMPLE:
        return False
    if assessment.status != "continue":
        return False
    if not state.step_results or any(not result.success for result in state.step_results):
        return False

    digest = state.prior_progress
    if digest is not None and digest.derived_progress_hint in ("high", "medium"):
        return True

    if len((state.evidence_summary or "").strip()) >= rules.simple_evidence_min_chars:
        return True

    return any(
        result.tool_call_count > 0 or result.subgraph_tool_call_count > 0
        for result in state.step_results
    )


def filter_filler_plan_steps(
    steps: list[StepAction],
    *,
    plan_rules: PlanSafetyRulesConfig | None = None,
) -> list[StepAction]:
    """Drop configured no-op tail steps such as ``Stop`` / ``The end``."""
    patterns = _filler_patterns(plan_rules)
    filtered = [
        step
        for step in steps
        if not any(pattern.match((step.description or "").strip()) for pattern in patterns)
    ]
    return filtered if filtered else steps


def render_plan_coverage(state: LoopState) -> str:
    """Render deterministic plan step coverage for assess prompts (IG-557)."""
    decision = state.current_decision
    if decision is None or not decision.steps:
        return ""
    completed = state.dependency_completion_ids()
    total = len(decision.steps)
    completed_count = sum(1 for step in decision.steps if step.id in completed)
    remaining = [step.id for step in decision.steps if step.id not in completed]
    ready = decision.get_ready_steps(completed)
    ready_ids = [step.id for step in ready]
    lines = [
        f"completed_steps: {completed_count}/{total}",
        f"remaining_step_ids: {', '.join(remaining) if remaining else '(none)'}",
        f"ready_steps: {', '.join(ready_ids) if ready_ids else '(none)'}",
        "note: Plan remaining ≠ goal complete; judge GOAL against evidence.",
    ]
    return "\n".join(lines)


def _progress_index(progress: str) -> int:
    return _PROGRESS_BUCKETS.index(progress)


def normalize_status_assessment(assessment: StatusAssessment) -> StatusAssessment:
    """Coerce structurally inconsistent assess output (IG-640, no content heuristics)."""
    if assessment.status != "done":
        return assessment

    updates: dict[str, object] = {}
    if assessment.goal_progress in ("none", "low"):
        updates["status"] = "replan"
        updates["goal_progress"] = "none"
    elif assessment.terminal_readiness != "ready":
        updates["status"] = "replan"
    elif not assessment.gap_alignment:
        updates["status"] = "replan"

    if not updates:
        return assessment

    logger.warning(
        "[Plan] Coerce inconsistent assess: status=done prog=%s readiness=%s gap_align=%s → %s",
        assessment.goal_progress,
        assessment.terminal_readiness,
        assessment.gap_alignment,
        updates.get("status", assessment.status),
    )
    return assessment.model_copy(update=updates)


def _open_gap_components(gap: PlanGapAnalysis | None) -> list[GoalComponentStatus]:
    if gap is None:
        return []
    return [
        component
        for component in gap.components
        if component.status in ("not_started", "partial", "blocked")
    ]


def terminal_assess_may_complete(
    state: LoopState,
    assessment: StatusAssessment,
    gap: PlanGapAnalysis | None,
    *,
    intake_label: IntakeLabel | None = None,
) -> bool:
    """Return True when assess may route to goal completion (typed structural gates only)."""
    is_terminal = assessment.status == "done" or assessment.goal_progress == "complete"
    if not is_terminal:
        return False

    if assessment.status == "done":
        min_idx = _progress_index(_MIN_GOAL_PROGRESS_FOR_DONE)
        if _progress_index(assessment.goal_progress) < min_idx:
            return False

    if not assess_may_route_complete(state, assessment, intake_label):
        return False

    if not assess_respects_gap_analysis(assessment, gap):
        return False

    if gap is not None:
        if gap.distance_from_goal != "at_goal":
            return False
        if _open_gap_components(gap):
            return False

    if not assessment.gap_alignment:
        return False

    intent = getattr(state, "intent", None)
    multi_phase = getattr(intent, "multi_phase", None) if intent is not None else None
    if multi_phase:
        if assessment.goal_progress != "complete" or assessment.terminal_readiness != "ready":
            return False

    digest = state.prior_progress
    if digest is not None:
        try:
            hint_idx = _progress_index(digest.derived_progress_hint)
            llm_idx = _progress_index(assessment.goal_progress)
        except ValueError:
            pass
        else:
            if abs(hint_idx - llm_idx) > _DIGEST_DISAGREEMENT_BUCKET_THRESHOLD:
                return False

    if state.step_results:
        if any(r.had_recoverable_tool_errors for r in state.step_results):
            if assessment.goal_progress != "complete" or assessment.terminal_readiness != "ready":
                return False

    return True


def assess_may_route_complete(
    state: LoopState,
    assessment: StatusAssessment,
    intake_label: IntakeLabel | None,
) -> bool:
    """Return False when routing ``goal_progress=complete`` would be premature."""
    if assessment.goal_progress != "complete":
        return True

    if intake_label != IntakeLabel.COMPLEX:
        return True

    from soothe.foundation.sloop.prompts.plan_ledger_projection import (
        _current_goal_has_execute_ledger,
    )

    if not state.step_results and not _current_goal_has_execute_ledger(state):
        return False
    return not state.has_remaining_steps()


def assess_respects_gap_analysis(
    assessment: StatusAssessment,
    gap: PlanGapAnalysis | None,
) -> bool:
    """Return False when assess contradicts gap analysis (IG-557, IG-640)."""
    if gap is None:
        return True
    if gap.distance_from_goal in ("far", "moderate", "near"):
        if assessment.goal_progress == "complete" or assessment.status == "done":
            return False
    open_components = _open_gap_components(gap)
    if open_components and (assessment.goal_progress == "complete" or assessment.status == "done"):
        return False
    return True
