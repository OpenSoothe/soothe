"""Loop Graph channel schema for LangGraph routing (RFC-220)."""

from __future__ import annotations

from typing import Any, Literal, TypedDict

IterationOutcome = Literal["continue", "completed", "fatal", "max_iterations", "deferred"]

PlanRoute = Literal["goal_done", "execute"]
IntentRoute = Literal["continue_loop", "fast_path"]
AssessRoute = Literal["continue_generate", "skip_generate", "continue_assess"]
ClarificationOrigin = Literal["execute", "plan_generate", "plan_assess"]

PLAN_ROUTE_GOAL_DONE: PlanRoute = "goal_done"
PLAN_ROUTE_EXECUTE: PlanRoute = "execute"


class LoopGraphState(TypedDict, total=False):
    """Channels merged between Loop Graph nodes."""

    last_outcome: IterationOutcome | None
    plan_route: PlanRoute | None
    intent_route: IntentRoute | None
    assess_route: AssessRoute | None
    # Clarification relay (RFC-622): serialized to keep the channel JSON-safe.
    pending_clarification: dict[str, Any] | None
    pending_clarification_answer: dict[str, Any] | None
    last_clarification_origin: ClarificationOrigin | None
    # Set true when execute_steps synthesizes a step result on the
    # clarification-resume path (no scratch decision / plan_result). Routing
    # skips record_iteration in that case to avoid the "missing plan or
    # decision" fatal — the synthesized step has already emitted
    # step_completed and the next iteration will replan from the answer.
    resume_synth: bool | None
