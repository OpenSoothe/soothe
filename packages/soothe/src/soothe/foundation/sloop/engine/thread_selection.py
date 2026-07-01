"""Thread selection logic for execute steps (RFC-223, IG-477, IG-349).

Functions for selecting thread IDs during parallel step execution and
subagent routing detection.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from soothe.foundation.sloop.state.schemas import AgentDecision, LoopState, StepAction


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


def resolve_wire_subagent_for_step(
    step: Any,
    routing_classification: Any | None,
) -> str | None:
    """Resolve subagent wiring for execute: planner step hint wins over wire routing."""
    wire = getattr(step, "wire_subagent", None)
    if isinstance(wire, str) and wire.strip():
        return wire.strip()
    return _wire_subagent_from_routing(routing_classification)


def _select_thread_for_step(
    step: StepAction,
    decision: AgentDecision,
    state: LoopState,
    main_thread_id: str,
) -> str:
    """Select an isolated thread_id for a step.

    IG-477: Thread isolation via ``__step_<id>`` namespace for parallel safety.
    Predecessor context arrives via message injection, not checkpoint fork.

    Strategy:
    | Direct deps | Action                                              |
    |-------------|-----------------------------------------------------|
    | 0           | new __step_<id> thread                              |
    | ≥1          | new __step_<id> thread + predecessor msg injection |

    Returns:
        Thread_id for the step's CoreAgent execution.
    """
    direct_deps = step.dependencies or []

    if not direct_deps:
        return f"{main_thread_id}__step_{step.id}"

    return f"{main_thread_id}__step_{step.id}"


__all__ = [
    "_select_thread_for_step",
    "_wire_subagent_from_routing",
    "resolve_wire_subagent_for_step",
]
