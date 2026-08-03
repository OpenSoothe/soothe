"""Mid-loop intake-tier policy (IG-676).

Fresh goals use special graph entry (inject / skip-evaluate). Mid-loop goals
share one spine entry (``gather_evidence``); intake only tunes station behavior.
"""

from __future__ import annotations

from soothe.sloop.intention.models import IntakeLabel

__all__ = [
    "mid_loop_allow_inventory",
    "mid_loop_skip_continuation_assess",
    "mid_loop_use_lightweight_generate",
]


def mid_loop_skip_continuation_assess(intake_label: IntakeLabel | None) -> bool:
    """True when new mid-loop goals must skip ``assess_continuation`` LLM.

    Simple and complex never bootstrap; escalate to plan_generate instead.
    Trivial keeps the discriminator (bootstrap vs generate).
    """
    return intake_label in (IntakeLabel.SIMPLE, IntakeLabel.COMPLEX)


def mid_loop_use_lightweight_generate(intake_label: IntakeLabel | None) -> bool:
    """True when plan_generate should use the lightweight planner call."""
    return intake_label == IntakeLabel.SIMPLE


def mid_loop_allow_inventory(
    *,
    intake_label: IntakeLabel | None,
    projection_mode: str,
    has_step_results: bool,
    has_execute_ledger: bool,
) -> bool:
    """True when evaluate should run gap inventory before status assess.

    Structural skips only: trivial intake, or new_goal with no execute evidence.
    """
    if intake_label == IntakeLabel.TRIVIAL:
        return False
    if projection_mode == "new_goal" and not has_step_results and not has_execute_ledger:
        return False
    return True
