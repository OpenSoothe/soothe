"""Protocol, request/answer dataclasses, and (de)serialization helpers."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

ClarificationOrigin = Literal["execute", "plan_generate", "plan_assess"]


@dataclass(frozen=True)
class LoopStateView:
    """Read-only projection of loop state for clarification policies.

    Intentionally narrow: policies receive only what they need to answer
    a clarification, not the full mutable loop state.
    """

    goal_id: str
    goal_description: str
    user_request: str
    iteration: int
    intent_classification: str | None
    plan_summary: str | None
    recent_step_outputs: tuple[str, ...]
    workspace_summary: str | None
    active_skills: tuple[str, ...]
    active_mcp_servers: tuple[str, ...]


@dataclass(frozen=True)
class ClarificationRequest:
    questions: tuple[str, ...]
    origin_node: ClarificationOrigin
    origin_interrupt_id: str
    loop_state: LoopStateView


@dataclass(frozen=True)
class ClarificationAnswer:
    answers: tuple[str, ...]
    source: Literal["human", "veritas", "fallback"]
    confidence: float | None = None
    defer: bool = False
    audit: Mapping[str, Any] = field(default_factory=dict)


class ClarificationDeferredError(Exception):
    """Raised by a policy when no answer is available.

    ``await_clarification`` translates this into ``awaiting_clarification``
    goal status and terminates the loop until the question is answered
    out-of-band (e.g. by ``soothe goal answer ...``).
    """

    def __init__(self, reason: str, request: ClarificationRequest) -> None:
        super().__init__(reason)
        self.reason = reason
        self.request = request


class ClarificationPolicy(Protocol):
    """Resolve a :class:`ClarificationRequest` into a :class:`ClarificationAnswer`.

    Implementations: :class:`InteractiveClarificationPolicy` (TUI relay) and
    :class:`AutoClarificationPolicy` (``veritas`` subagent).
    """

    async def answer(self, request: ClarificationRequest) -> ClarificationAnswer: ...


def _view_to_state(view: LoopStateView) -> dict[str, Any]:
    return {
        "goal_id": view.goal_id,
        "goal_description": view.goal_description,
        "user_request": view.user_request,
        "iteration": view.iteration,
        "intent_classification": view.intent_classification,
        "plan_summary": view.plan_summary,
        "recent_step_outputs": list(view.recent_step_outputs),
        "workspace_summary": view.workspace_summary,
        "active_skills": list(view.active_skills),
        "active_mcp_servers": list(view.active_mcp_servers),
    }


def _view_from_state(d: Mapping[str, Any]) -> LoopStateView:
    return LoopStateView(
        goal_id=str(d.get("goal_id", "")),
        goal_description=str(d.get("goal_description", "")),
        user_request=str(d.get("user_request", "")),
        iteration=int(d.get("iteration", 0)),
        intent_classification=d.get("intent_classification"),
        plan_summary=d.get("plan_summary"),
        recent_step_outputs=tuple(d.get("recent_step_outputs", []) or []),
        workspace_summary=d.get("workspace_summary"),
        active_skills=tuple(d.get("active_skills", []) or []),
        active_mcp_servers=tuple(d.get("active_mcp_servers", []) or []),
    )


def request_to_state(req: ClarificationRequest) -> dict[str, Any]:
    """Serialize a request for LangGraph channel storage (JSON-safe)."""
    return {
        "questions": list(req.questions),
        "origin_node": req.origin_node,
        "origin_interrupt_id": req.origin_interrupt_id,
        "loop_state": _view_to_state(req.loop_state),
    }


def request_from_state(d: Mapping[str, Any]) -> ClarificationRequest:
    """Inverse of :func:`request_to_state`."""
    origin = d.get("origin_node")
    if origin not in ("execute", "plan_generate", "plan_assess"):
        msg = f"invalid origin_node: {origin!r}"
        raise ValueError(msg)
    return ClarificationRequest(
        questions=tuple(d.get("questions", []) or []),
        origin_node=origin,
        origin_interrupt_id=str(d.get("origin_interrupt_id", "")),
        loop_state=_view_from_state(d.get("loop_state", {})),
    )


def answer_to_state(ans: ClarificationAnswer) -> dict[str, Any]:
    """Serialize an answer for LangGraph channel storage (JSON-safe)."""
    return {
        "answers": list(ans.answers),
        "source": ans.source,
        "confidence": ans.confidence,
        "defer": ans.defer,
        "audit": dict(ans.audit),
    }


def answer_from_state(d: Mapping[str, Any]) -> ClarificationAnswer:
    """Inverse of :func:`answer_to_state`."""
    source = d.get("source")
    if source not in ("human", "veritas", "fallback"):
        msg = f"invalid source: {source!r}"
        raise ValueError(msg)
    return ClarificationAnswer(
        answers=tuple(d.get("answers", []) or []),
        source=source,
        confidence=d.get("confidence"),
        defer=bool(d.get("defer", False)),
        audit=dict(d.get("audit", {}) or {}),
    )
