"""Merge intent classification with wire ``preferred_subagent`` for AgentLoop (IG-349)."""

from __future__ import annotations

from typing import Any


def build_loop_routing_classification(
    intent: Any | None,
    preferred_subagent: str | None,
) -> Any | None:
    """Build ``RoutingClassification`` for ``LoopState.routing_classification`` (IG-383).

    When ``intent`` is None (e.g. classifier disabled), still honors ``preferred_subagent``.

    Args:
        intent: ``IntentClassification`` or None.
        preferred_subagent: Optional wire hint from slash routing.

    Returns:
        ``RoutingClassification`` or None when neither source applies.
    """
    from soothe.core.intention import RoutingClassification

    if intent is None:
        if preferred_subagent:
            return RoutingClassification(
                task_complexity="medium",
                preferred_subagent=preferred_subagent,
                routing_hint="subagent",
            )
        return None

    tc = _intent_task_complexity_to_routing(getattr(intent, "task_complexity", "medium"))
    base = RoutingClassification(
        task_complexity=tc,
        chitchat_response=getattr(intent, "chitchat_response", None),
        preferred_subagent=None,
        routing_hint="intent_based",
    )
    if preferred_subagent:
        return base.model_copy(
            update={"preferred_subagent": preferred_subagent, "routing_hint": "subagent"}
        )
    return base


# Back-compat name (IG-349 era)
build_loop_unified_classification = build_loop_routing_classification


def _intent_task_complexity_to_routing(tc: str) -> str:
    """Map ``IntentClassification.task_complexity`` to ``RoutingClassification`` literals."""
    if tc == "chitchat":
        return "chitchat"
    if tc == "complex":
        return "complex"
    return "medium"
