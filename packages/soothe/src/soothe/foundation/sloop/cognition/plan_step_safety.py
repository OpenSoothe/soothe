"""Plan step safety helpers for simple-intake goals (post-search blow-up guard)."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from soothe.foundation.sloop.intention.models import IntakeLabel
from soothe.foundation.sloop.state.schemas import (
    AgentDecision,
    PlanGapAnalysis,
    StatusAssessment,
    StepAction,
)

if TYPE_CHECKING:
    from soothe.foundation.sloop.state.schemas import LoopState

# IG-555: max plan_generate retries when complex iter=0 plans stay undersized.
MAX_UNDERSIZED_PLAN_REPLANS = 2

_FILLER_STEP_RE = re.compile(
    r"^(wrap up|conclude|terminate|stop|halt|cease|end process|close|exit|quit|"
    r"finish up|complete process|final step|last step|the end)$",
    re.IGNORECASE,
)

_SIMPLE_EVIDENCE_MIN_CHARS = 200


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
    """Return True when a plan satisfies the complex-intake minimum step count (IG-555).

    Complex intake at iter=0 must produce at least two steps before execution.
    Simple/trivial intake may legitimately use a single step. After execution
    (iter>0), replan may consolidate to fewer steps.

    Args:
        decision: Current or generated plan decision.
        intake_label: Intake classification from intent_classify.
        iteration: Current loop iteration.
        treat_missing_as_undersized: When False, a missing decision passes the
            guard (used after plan_generate when no executable plan was returned).

    Returns:
        True when the plan satisfies the minimum step requirement.
    """
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
) -> bool:
    """True when a ``simple`` goal has enough evidence to skip another plan wave."""
    if intake_label_from_state(state) != IntakeLabel.SIMPLE:
        return False
    if assessment.status != "continue":
        return False
    if not state.step_results or any(not result.success for result in state.step_results):
        return False

    digest = state.prior_progress
    if digest is not None and digest.derived_progress_hint in ("high", "medium"):
        return True

    if len((state.evidence_summary or "").strip()) >= _SIMPLE_EVIDENCE_MIN_CHARS:
        return True

    return any(
        result.tool_call_count > 0 or result.subgraph_tool_call_count > 0
        for result in state.step_results
    )


def filter_filler_plan_steps(steps: list[StepAction]) -> list[StepAction]:
    """Drop obvious no-op tail steps such as ``Stop`` / ``The end``."""
    filtered = [
        step for step in steps if not _FILLER_STEP_RE.match((step.description or "").strip())
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
    """Return False when assess contradicts gap analysis (IG-557)."""
    if gap is None:
        return True
    if gap.distance_from_goal in ("far", "moderate"):
        if assessment.goal_progress == "complete" or assessment.status == "done":
            return False
    open_components = [
        component
        for component in gap.components
        if component.status in ("not_started", "partial", "blocked")
    ]
    if open_components and assessment.goal_progress == "complete":
        return False
    return True
