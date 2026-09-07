"""Wire events for the clarification relay."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import ConfigDict
from soothe_sdk.core.events import (
    LOOP_CLARIFICATION_ANSWERED,
    LOOP_CLARIFICATION_DEFERRED,
    LOOP_CLARIFICATION_REQUESTED,
    SootheEvent,
)
from soothe_sdk.core.verbosity import VerbosityTier

from soothe.events import register_event


class ClarificationRequestedEvent(SootheEvent):
    """Fired when `await_clarification` enters with a pending question."""

    type: Literal["soothe.loop.clarification.requested"] = LOOP_CLARIFICATION_REQUESTED  # type: ignore[assignment]
    # RFC-622 §9c: questions may be structured dicts (QuestionSpec with
    # question/header/options) or plain strings (HITL / degraded fallback).
    # Use list[Any] so the wire event accepts both without validation errors.
    questions: list[Any] = []
    origin_node: str = ""
    mode: Literal["manual", "auto"] = "manual"
    # RFC-633 planner-subagent review card (empty for other origins).
    plan_path: str = ""
    plan_markdown: str = ""
    # Step id of the paused step (when origin is execute / tool_approval).
    # The TUI uses this to show "awaiting answer" on the existing step card
    # instead of marking it complete. Empty for plan-mode review and other
    # non-step origins.
    step_id: str = ""

    model_config = ConfigDict(extra="allow")


class ClarificationAnsweredEvent(SootheEvent):
    """Fired after the policy returns an answer."""

    type: Literal["soothe.loop.clarification.answered"] = LOOP_CLARIFICATION_ANSWERED  # type: ignore[assignment]
    source: Literal["human", "veritas", "fallback"] = "human"
    confidence: float | None = None
    defer: bool = False

    model_config = ConfigDict(extra="allow")


class ClarificationDeferredEvent(SootheEvent):
    """Fired when the policy raises `ClarificationDeferredError`."""

    type: Literal["soothe.loop.clarification.deferred"] = LOOP_CLARIFICATION_DEFERRED  # type: ignore[assignment]
    reason: str = ""
    question_summary: str = ""
    # RFC-622 §9c: same as ClarificationRequestedEvent — structured dicts or strings.
    questions: list[Any] = []
    # RFC-623 taxonomy: explicit | low_confidence | structured_output_failed | answer_was_question
    defer_kind: str = ""

    model_config = ConfigDict(extra="allow")


register_event(
    ClarificationRequestedEvent,
    verbosity=VerbosityTier.NORMAL,
    summary_template="Clarification needed: {questions}",
)
register_event(
    ClarificationAnsweredEvent,
    verbosity=VerbosityTier.NORMAL,
    summary_template="Clarification answered ({source})",
)
register_event(
    ClarificationDeferredEvent,
    verbosity=VerbosityTier.NORMAL,
    summary_template="Clarification deferred: {reason}",
)


__all__ = [
    "ClarificationAnsweredEvent",
    "ClarificationDeferredEvent",
    "ClarificationRequestedEvent",
]
