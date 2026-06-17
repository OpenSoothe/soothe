"""Thread selection logic for execute steps (RFC-223, IG-477, IG-349).

This module provides functions for selecting thread IDs during parallel
step execution, including sole-child chain reuse optimization and
subagent routing detection.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from soothe.foundation.loop.state.schemas import AgentDecision, LoopState, StepAction


logger = logging.getLogger(__name__)


def _wire_subagent_from_routing(routing_classification: Any | None) -> str | None:
    """Subagent name when wire routing requests explicit subagent delegation (IG-349)."""
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


def _count_dependents(predecessor_id: str, decision: AgentDecision) -> int:
    """Count how many steps in ``decision`` directly depend on ``predecessor_id``.

    Used for sole-child chain reuse: when only one step depends on a given
    predecessor, that step can reuse the predecessor's thread_id directly
    without creating a new namespace.
    """
    count = 0
    for s in getattr(decision, "steps", None) or []:
        deps = getattr(s, "dependencies", None) or []
        if predecessor_id in deps:
            count += 1
    return count


def _select_thread_for_step(
    step: StepAction,
    decision: AgentDecision,
    state: LoopState,
    main_thread_id: str,
) -> str:
    """Select thread_id for a step with sole-child chain reuse optimization.

    IG-477: Thread isolation via __step_<id> namespace for parallel safety.
    Predecessor context arrives via message injection, not checkpoint fork.

    Strategy:
    | Direct deps | Predecessor's other dependents | Action                     |
    |-------------|--------------------------------|----------------------------|
    | 0           | n/a                            | new __step_<id> thread     |
    | 1           | 0 (sole child)                 | reuse predecessor's thread |
    | 1           | ≥1 (has siblings)              | new __step_<id> thread     |
    | ≥2          | n/a                            | new __step_<id> thread     |

    Returns:
        Thread_id for the step's CoreAgent execution.
    """
    direct_deps = step.dependencies or []

    # No dependencies → fresh isolated thread
    if not direct_deps:
        return f"{main_thread_id}__step_{step.id}"

    # Multiple dependencies → fresh isolated thread (predecessor context via message injection)
    if len(direct_deps) > 1:
        return f"{main_thread_id}__step_{step.id}"

    # Singleton dependency
    pred_step_id = direct_deps[0]
    pred_thread_id = state.step_thread_ids.get(pred_step_id)

    # Predecessor thread not tracked → fresh isolated thread
    if not pred_thread_id:
        logger.debug(
            "Predecessor thread not found for step %s (dep: %s), creating new thread",
            step.id,
            pred_step_id,
        )
        return f"{main_thread_id}__step_{step.id}"

    # Sole-child optimization: reuse predecessor's thread when no siblings
    if _count_dependents(pred_step_id, decision) <= 1:
        logger.debug(
            "Sole-child reuse: step %s reusing predecessor %s's thread %s",
            step.id,
            pred_step_id,
            pred_thread_id,
        )
        return pred_thread_id

    # Has siblings → new isolated thread to prevent namespace collision
    return f"{main_thread_id}__step_{step.id}"


__all__ = [
    "_count_dependents",
    "_select_thread_for_step",
    "_wire_subagent_from_routing",
]
