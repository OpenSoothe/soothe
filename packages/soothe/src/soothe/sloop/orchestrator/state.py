"""Loop Graph channel schema for LangGraph routing (RFC-220, RFC-630, IG-554)."""

from __future__ import annotations

from typing import Any, Literal, TypedDict

from soothe.sloop.clarification.origins import ClarificationOrigin
from soothe.sloop.intention.models import IntakeLabel

IterationOutcome = Literal["continue", "completed", "fatal", "max_iterations", "deferred"]

PlanRoute = Literal["goal_done", "execute"]
IntentRoute = Literal["continue_loop", "fast_path", "wired_subagent"]
AssessRoute = Literal["continue_generate", "skip_generate"]
EvidenceGatherRoute = Literal[
    "evaluate",
    "plan_generate_skip_evaluate",
    "keep_plan",
]

PLAN_ROUTE_GOAL_DONE: PlanRoute = "goal_done"
PLAN_ROUTE_EXECUTE: PlanRoute = "execute"


class LoopGraphState(TypedDict, total=False):
    """Channels merged between Loop Graph nodes."""

    last_outcome: IterationOutcome | None
    plan_route: PlanRoute | None
    intent_route: IntentRoute | None
    assess_route: AssessRoute | None
    evidence_gather_route: EvidenceGatherRoute | None
    # RFC-630: 4-class intake label set by enter_loop, read by
    # route_after_preprocess to dispatch to chitchat/trivial/simple/complex branches.
    intake_label: IntakeLabel | None
    # RFC-630: structural continuation overlay set by enter_loop from
    # checkpoint state (continue_loop_mode + prior completed goals). When True,
    # route_after_preprocess dispatches via evaluate / gather_evidence overlays.
    is_continuation: bool | None
    # IG-554: True when daemon created a new goal record (fresh loop or new goal
    # on idle loop). Used by route_after_preprocess routing guard to block chitchat
    # fast-path when structural admission contradicts social classification.
    new_goal_created: bool | None
    # IG-554: derived intake fields for routing and downstream consumers.
    is_task: bool | None
    scope: IntakeLabel | None
    has_deliverable: bool | None
    # Clarification relay (RFC-622): serialized to keep the channel JSON-safe.
    pending_clarification: dict[str, Any] | None
    pending_clarification_answer: dict[str, Any] | None
    last_clarification_origin: ClarificationOrigin | None
    # IG-660: Approve cleared planner wire; route_after_wired_subagent → generate_plan.
    planner_implement_handoff: bool | None
    # Set true when execute synthesizes a step result on the
    # clarification-resume path (no scratch decision / plan_result). Routing
    # skips record_progress in that case to avoid the "missing plan or
    # decision" fatal — the synthesized step has already emitted
    # step_completed and the next iteration will replan from the answer.
    resume_synth: bool | None
    # RFC-226 / terminal bootstrap: record_progress → finalize.
    after_record_route: Literal["finalize", "goal_completion", ""] | None
