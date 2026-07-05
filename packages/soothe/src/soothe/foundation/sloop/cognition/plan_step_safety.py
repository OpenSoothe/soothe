"""Plan step safety helpers for simple-intake goals (post-search blow-up guard)."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from soothe.foundation.sloop.intention.models import IntakeLabel
from soothe.foundation.sloop.state.schemas import FIRST_WAVE_MAX_STEPS, StatusAssessment, StepAction

if TYPE_CHECKING:
    from soothe.foundation.sloop.state.schemas import LoopState

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


def max_plan_steps_for_state(state: LoopState) -> int | None:
    """Return the per-wave step cap for plan-generate, if any."""
    if state.iteration == 0 or intake_label_from_state(state) == IntakeLabel.SIMPLE:
        return FIRST_WAVE_MAX_STEPS
    return None


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
