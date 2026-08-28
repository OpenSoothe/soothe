"""Thread selection logic for execute steps."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from soothe.sloop.orchestrator.checkpoint import execute_step_thread_id

if TYPE_CHECKING:
    from soothe.sloop.state.schemas import AgentDecision, LoopState, StepAction

logger = logging.getLogger(__name__)


def _wire_subagent_from_routing(routing_classification: Any | None) -> str | None:
    """Subagent name when wire routing requests explicit subagent delegation."""
    if routing_classification is None:
        return None
    if isinstance(routing_classification, dict):
        routing_hint = routing_classification.get("routing_hint")
        preferred = routing_classification.get("preferred_subagent")
    else:
        routing_hint = getattr(routing_classification, "routing_hint", None)
        preferred = getattr(routing_classification, "preferred_subagent", None)
    if routing_hint != "subagent" or not preferred:
        return None
    if isinstance(preferred, str):
        stripped = preferred.strip()
        return stripped or None
    return str(preferred) if preferred is not None else None


def resolve_user_requested_wire_subagent(
    *,
    routing_classification: Any | None = None,
    preferred_subagent: str | None = None,
) -> str | None:
    """Return a wired subagent the user requested explicitly via slash routing."""
    from soothe.sloop.state.schemas import resolve_wire_subagent

    for candidate in (
        preferred_subagent,
        _wire_subagent_from_routing(routing_classification),
    ):
        resolved = resolve_wire_subagent(wire_subagent=candidate)
        if resolved:
            return resolved
    return None


def _is_only_child(parent_id: str, decision: AgentDecision) -> bool:
    """True when `parent_id` has exactly one child in the decision's step list."""
    children = [s for s in decision.steps if parent_id in (s.dependencies or [])]
    return len(children) == 1


def _select_thread_for_step(
    step: StepAction,
    main_thread_id: str,
    *,
    decision: AgentDecision | None = None,
    loop_state: LoopState | None = None,
    is_clarification_resume: bool = False,
) -> str:
    """Select a thread_id for a step.

    Reuse rules (only one must hold to reuse a parent thread):

    - **Interrupt resume** (`is_clarification_resume=True`): reuse the
      thread_id stored in `loop_state.resume_ticket.thread_id` so
      `Command(resume=...)` finds the pending interrupt.
    - **Strict linear chain**: step has exactly 1 dependency AND the parent
      has exactly 1 child (no fan-out). Reuse the parent's thread_id.

    All other cases get a new random thread_id.
    """
    step_thread_ids = getattr(loop_state, "step_thread_ids", {}) if loop_state else {}

    # Condition B: interrupt resume — must reuse the original thread.
    if is_clarification_resume:
        resume_ticket = getattr(loop_state, "resume_ticket", None) if loop_state else None
        resume_tid = resume_ticket.thread_id if resume_ticket else None
        if resume_tid:
            logger.info("[thread] resume: reusing interrupted thread %s", resume_tid[:24])
            return resume_tid
        # Fallback: try the step's prior thread_id (step was re-activated, same ID).
        prior = step_thread_ids.get(step.id)
        if prior:
            logger.info("[thread] resume: reusing prior step thread %s", prior[:24])
            return prior

    # Condition A: strict linear chain — reuse parent's thread.
    if decision is not None and step.dependencies and len(step.dependencies) == 1:
        parent_id = step.dependencies[0]
        parent_thread = step_thread_ids.get(parent_id)
        if parent_thread and _is_only_child(parent_id, decision):
            logger.info(
                "[thread] linear reuse: step %s inherits parent %s thread %s",
                step.id,
                parent_id,
                parent_thread[:24],
            )
            return parent_thread

    # Default: new isolated thread.
    return execute_step_thread_id(main_thread_id)


__all__ = [
    "_is_only_child",
    "_select_thread_for_step",
    "_wire_subagent_from_routing",
    "resolve_user_requested_wire_subagent",
]
