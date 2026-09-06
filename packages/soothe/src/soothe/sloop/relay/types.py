"""Core data types for the unified interrupt relay.

Single-interrupt design: only the CoreAgent calls LangGraph `interrupt()`
(to pause mid-tool). The StrangeLoop never calls `interrupt()` — it exits
cleanly and is re-invoked when the answer arrives.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal

from soothe.sloop.clarification.protocol import (
    ClarificationAnswer,
    ClarificationRequest,
)

ClarificationStatus = Literal[
    "captured",
    "parked",
    "answered",
    "consumed",
    "failed",
]
"""Lifecycle status of a clarification row."""

PolicyMode = Literal["auto", "manual"]
"""Clarification mode frozen at capture time."""

AnswerSource = Literal["human", "veritas", "static", "retry"]

RelayDeferKind = Literal[
    "explicit",
    "low_confidence",
    "structured_output_failed",
    "answer_was_question",
    "manual",
    "queue_full",
    "manual_timeout",
    "retry_limit",
]


@dataclass(frozen=True)
class RelayHandle:
    """In-memory handle returned by `capture()`.

    Attributes:
        relay_id: UUID key in the `clarifications` table.
        origin: Clarification origin.
        request: The structured clarification request.
        core_agent_thread_id: CoreAgent thread with the suspended interrupt.
        step_id: Originating step id.
        step_description: Human-readable step label.
    """

    relay_id: str
    origin: str
    request: ClarificationRequest
    core_agent_thread_id: str | None = None
    step_id: str | None = None
    step_description: str | None = None


@dataclass(frozen=True)
class CoreAgentResumeSpec:
    """CoreAgent resume payload injected into the executor stream.

    Attributes:
        thread_id: CoreAgent thread hosting the suspended interrupt.
        resume_payload: Origin-specific `Command(resume=...)` value.
    """

    thread_id: str
    resume_payload: dict[str, Any]


@dataclass(frozen=True)
class ResumeDirective:
    """Resume plan for re-invoking the StrangeLoop graph.

    Attributes:
        relay_id: The clarification row's durable key.
        graph_input: StrangeLoop graph input dict.
        core_agent_resume: CoreAgent resume spec, or `None` for non-in-graph origins.
        resume_station: Station to route to after the answer is processed.
    """

    relay_id: str
    graph_input: dict[str, Any]
    core_agent_resume: CoreAgentResumeSpec | None = None
    resume_station: str = "EXECUTE"


@dataclass(frozen=True)
class ParkOutcome:
    """Result of parking a clarification.

    Attributes:
        kind: `awaiting_human` (manual park), `answered` (auto inline), or `deferred`.
        relay_id: The clarification row's durable key.
        answer: The answer when `kind == "answered"`.
        defer_kind: Defer taxonomy value when `kind == "deferred"`.
    """

    kind: Literal["awaiting_human", "answered", "deferred"]
    relay_id: str
    answer: ClarificationAnswer | None = None
    defer_kind: RelayDeferKind | None = None


@dataclass(frozen=True)
class SubmitResult:
    """Result of submitting an answer.

    Attributes:
        status: `ok`, `already_answered` (idempotent), `circuit_breaker`, or `invalid_schema`.
        relay_id: The clarification row's durable key.
        stored_answer: The stored answer (for idempotent duplicates).
    """

    status: Literal["ok", "already_answered", "circuit_breaker", "invalid_schema"]
    relay_id: str
    stored_answer: ClarificationAnswer | None = None


@dataclass(frozen=True)
class ReconcileReport:
    """Three-way consistency check result.

    Attributes:
        consistent: `True` when all three stores agree.
        relay_status: Status from the relay store.
        ce_goal_status: Status from the Context Engine.
        core_agent_thread_ok: `True` when the CoreAgent thread still has a live interrupt.
        conflict: Diagnostic when `consistent` is `False`.
    """

    consistent: bool
    relay_status: ClarificationStatus | None = None
    ce_goal_status: str | None = None
    core_agent_thread_ok: bool | None = None
    conflict: str | None = None


@dataclass(frozen=True)
class RelayGraphProjection:
    """Projection of a relay handle into StrangeLoop graph channels.

    Attributes:
        pending_clarification: Serialized request for `await_clarification`.
        resume_relay_id: The relay row's durable key.
        last_clarification_origin: Origin for `route_after_clarification`.
    """

    pending_clarification: dict[str, Any]
    resume_relay_id: str
    last_clarification_origin: str


def projection_to_state(projection: RelayGraphProjection) -> dict[str, Any]:
    """Serialize a projection for LangGraph channel storage."""
    return {
        "pending_clarification": dict(projection.pending_clarification),
        "resume_relay_id": projection.resume_relay_id,
        "last_clarification_origin": projection.last_clarification_origin,
    }


def projection_from_state(d: Mapping[str, Any]) -> RelayGraphProjection | None:
    """Inverse of `projection_to_state`. Returns `None` when no projection."""
    pending = d.get("pending_clarification")
    relay_id = d.get("resume_relay_id")
    if not pending or not relay_id:
        return None
    origin = str(d.get("last_clarification_origin", ""))
    return RelayGraphProjection(
        pending_clarification=dict(pending) if isinstance(pending, Mapping) else {},
        resume_relay_id=str(relay_id),
        last_clarification_origin=origin,
    )


__all__ = [
    "AnswerSource",
    "ClarificationStatus",
    "CoreAgentResumeSpec",
    "ParkOutcome",
    "PolicyMode",
    "RelayDeferKind",
    "RelayGraphProjection",
    "RelayHandle",
    "ReconcileReport",
    "ResumeDirective",
    "SubmitResult",
    "projection_from_state",
    "projection_to_state",
]
