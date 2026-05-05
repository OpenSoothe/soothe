"""Merge intent classification with explicit subagent routing hints."""

from __future__ import annotations

from typing import Any

from .models import RoutingClassification


def build_loop_routing_classification(
    intent: Any | None,
    preferred_subagent: str | None,
) -> RoutingClassification | None:
    """Build routing classification consumed by AgentLoop Plan/Execute."""
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


def _intent_task_complexity_to_routing(tc: str) -> str:
    """Map intent task complexity to routing complexity."""
    if tc == "chitchat":
        return "chitchat"
    if tc == "simple":
        return "simple"
    if tc == "complex":
        return "complex"
    return "medium"
