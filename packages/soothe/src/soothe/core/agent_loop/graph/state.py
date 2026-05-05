"""Loop Graph channel schema for LangGraph routing (RFC-220)."""

from __future__ import annotations

from typing import Literal, TypedDict

IterationOutcome = Literal["continue", "completed", "fatal", "max_iterations"]

PlanRoute = Literal["goal_done", "execute"]
IntentRoute = Literal["continue_loop", "fast_path"]

PLAN_ROUTE_GOAL_DONE: PlanRoute = "goal_done"
PLAN_ROUTE_EXECUTE: PlanRoute = "execute"


class LoopGraphState(TypedDict, total=False):
    """Channels merged between Loop Graph nodes."""

    last_outcome: IterationOutcome | None
    plan_route: PlanRoute | None
    intent_route: IntentRoute | None
