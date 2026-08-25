"""Thread selection logic for execute steps (RFC-223).

Thread IDs are **decoupled from step IDs**: each new step gets a random
5-hex thread_id (e.g. ``{loop_id}__a3f7c``), stored in
``LoopState.step_thread_ids[step.id]``. Thread reuse happens only in two
cases:

1. **Strict linear chain**: the step has exactly 1 dependency, and the
   parent step has exactly 1 child (no fan-out). The parent's thread_id is
   reused so the child inherits accumulated context (file reads, search
   results) without re-reading the codebase.

2. **Interrupt resume**: the step is being resumed after an
   ``ask_user`` / ``action_requests`` interrupt. The original thread_id
   (stored in ``LoopState.resume_thread_id``) is reused so
   ``Command(resume=...)`` finds the pending interrupt in the checkpointer.

All other cases (parallel siblings, fan-in, root step) get a new random
thread_id.
"""

from __future__ import annotations

import logging
import secrets
from typing import TYPE_CHECKING, Any

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


def _generate_thread_id(main_thread_id: str) -> str:
    """Generate a random thread_id decoupled from step_id."""
    suffix = secrets.token_hex(3)[:5]  # 5 hex chars
    return f"{main_thread_id}__{suffix}"


def _is_only_child(parent_id: str, decision: AgentDecision) -> bool:
    """True when ``parent_id`` has exactly one child in the decision's step list."""
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

    - **Interrupt resume** (``is_clarification_resume=True``): reuse the
      thread_id stored in ``loop_state.resume_thread_id`` so
      ``Command(resume=...)`` finds the pending interrupt.
    - **Strict linear chain**: step has exactly 1 dependency AND the parent
      has exactly 1 child (no fan-out). Reuse the parent's thread_id.

    All other cases get a new random thread_id.
    """
    step_thread_ids = getattr(loop_state, "step_thread_ids", {}) if loop_state else {}

    # Condition B: interrupt resume — must reuse the original thread.
    if is_clarification_resume:
        resume_tid = getattr(loop_state, "resume_thread_id", None) if loop_state else None
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
                step.id, parent_id, parent_thread[:24],
            )
            return parent_thread

    # Default: new isolated thread.
    return _generate_thread_id(main_thread_id)


__all__ = [
    "_generate_thread_id",
    "_is_only_child",
    "_select_thread_for_step",
    "_wire_subagent_from_routing",
    "resolve_user_requested_wire_subagent",
]
