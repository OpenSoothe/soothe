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
    """Resolve catalog subagent wiring for execute: step hint wins over wire routing.

    Intake-only specialists never become ``soothe_step_subagent`` (IG-652): they
    run via ``invoke_wired_subagent`` direct ``ainvoke``, not CoreAgent ``task``.
    """
    from soothe.foundation.sloop.state.schemas import is_intake_only_wire_subagent

    wire = getattr(step, "wire_subagent", None)
    if isinstance(wire, str) and wire.strip():
        name = wire.strip()
        if is_intake_only_wire_subagent(name):
            return None
        return name
    from_routing = _wire_subagent_from_routing(routing_classification)
    if is_intake_only_wire_subagent(from_routing):
        return None
    return from_routing


def resolve_user_requested_wire_subagent(
    *,
    routing_classification: Any | None = None,
    intent: Any | None = None,
    preferred_subagent: str | None = None,
) -> str | None:
    """Return a wired subagent requested via slash, routing, or Pass 2.

    Precedence: ``preferred_subagent`` (slash/daemon) → routing classification →
    Pass 2 ``intent.wire_subagent``. All names are allowlist-filtered.
    """
    from soothe.foundation.sloop.state.schemas import resolve_wire_subagent

    for candidate in (
        preferred_subagent,
        _wire_subagent_from_routing(routing_classification),
        getattr(intent, "wire_subagent", None) if intent is not None else None,
    ):
        resolved = resolve_wire_subagent(wire_subagent=candidate)
        if resolved:
            return resolved
    return None


def _select_thread_for_step(
    step: StepAction,
    decision: AgentDecision,
    state: LoopState,
    main_thread_id: str,
) -> str:
    """Select an isolated thread_id for a step.

    IG-477: Thread isolation via ``__step_<id>`` namespace for parallel safety.
    Predecessor context arrives via ledger projection, not checkpoint fork.

    Strategy:
    | Direct deps | Action                                              |
    |-------------|-----------------------------------------------------|
    | 0           | new __step_<id> thread                              |
    | ≥1          | new __step_<id> thread + predecessor ledger projection |

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
    "resolve_user_requested_wire_subagent",
    "resolve_wire_subagent_for_step",
]
