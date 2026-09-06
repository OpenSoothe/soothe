"""Clarification origin constants."""

from __future__ import annotations

from typing import Final, Literal

from soothe.sloop.orchestrator.stations import EXECUTE

# --- Live StrangeLoop / host origins ----------------------------------------

ORIGIN_EXECUTE: Final = EXECUTE
"""CoreAgent execute-step `ask_user` clarification."""

ORIGIN_PLAN_MODE_REVIEW: Final = "plan_mode_review"
"""Human review gate after plan-mode draft (approve / reject / refine)."""

ORIGIN_RAIL_PAUSE: Final = "rail_pause"
"""LoopRail `pause_for_user` human gate; host-side Veritas only."""

ORIGIN_TOOL_APPROVAL: Final = "tool_approval"
"""Deepagents `HumanInTheLoopMiddleware` tool-action approval gate.

The executor captures `action_requests` interrupts here instead of
auto-approving them. The request resumes at `EXECUTE` (the step
containing the tool call)."""

ClarificationOrigin = Literal[
    "execute",
    "plan_mode_review",
    "rail_pause",
    "tool_approval",
]

CLARIFICATION_ORIGINS: frozenset[str] = frozenset(
    {
        ORIGIN_EXECUTE,
        ORIGIN_PLAN_MODE_REVIEW,
        ORIGIN_RAIL_PAUSE,
        ORIGIN_TOOL_APPROVAL,
    }
)

DEFAULT_FORCE_MANUAL_ORIGINS: tuple[str, ...] = (ORIGIN_PLAN_MODE_REVIEW,)
"""Origins that never use veritas auto-answer, even in auto mode.

`plan_mode_review` — the plan approve/reject/refine gate is a human call.

`tool_approval` is intentionally NOT in this list: in auto mode the
`tool_approval` origin is resolved by the multi-stage pipeline —
deterministic deny → safety → allow stages handle most tool actions without
an LLM. Veritas's security-approver prompt (see
`build_veritas_system_prompt_for_origin`) handles the ambiguous tail.
Operators who want tool actions to require a human can re-add
`tool_approval` to `ClarificationConfig.force_manual_origins` in config:
deny/safety stages still auto-reject dangerous actions (safety property),
but allow rules and veritas are skipped so every other tool action goes to
the human relay."""
PLAN_MODE_REVIEW_INTERRUPT_PREFIX: Final = "plan-mode-review:"
"""Interrupt prefix for plan-mode review clarifications."""


__all__ = [
    "CLARIFICATION_ORIGINS",
    "ClarificationOrigin",
    "DEFAULT_FORCE_MANUAL_ORIGINS",
    "ORIGIN_EXECUTE",
    "ORIGIN_PLAN_MODE_REVIEW",
    "ORIGIN_RAIL_PAUSE",
    "ORIGIN_TOOL_APPROVAL",
    "PLAN_MODE_REVIEW_INTERRUPT_PREFIX",
]
