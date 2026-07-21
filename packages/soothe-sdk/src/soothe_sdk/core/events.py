"""Base event classes for Soothe events.

This module provides the base event classes that all specific events inherit from.
Module-specific events are defined in their respective modules and registered via
``register_event()``.

All progress events use 4-segment type strings
``soothe.<domain>.<component>.<action>`` with six domains:
lifecycle, protocol, tool, subagent, output, error.
"""

from __future__ import annotations

import logging
from typing import Any

from pydantic import BaseModel, ConfigDict


class SootheEvent(BaseModel):
    """Base class for all Soothe progress events."""

    type: str

    model_config = ConfigDict(extra="allow")

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a plain dict for wire-format emission."""
        return self.model_dump(exclude_none=True)

    def emit(self, logger: logging.Logger) -> None:
        """Emit this event via the LangGraph stream writer.

        Note: This method requires host-side implementation.
        For SDK use, events are typically sent via WebSocket.

        SDK-side event base class: provides type definition and serialization.
        Host-side implementation provides actual emit.
        """
        pass


class LifecycleEvent(SootheEvent):
    """Loop and session lifecycle events."""


class ProtocolEvent(SootheEvent):
    """Core protocol activity events."""


class SubagentEvent(SootheEvent):
    """Subagent activity events."""


class OutputEvent(SootheEvent):
    """Content destined for user display."""


class ErrorEvent(SootheEvent):
    """Error events."""

    error: str


# Event type constants
# Wire-safe event type strings for CLI/TUI event processing
# Exposed at DEBUG and DETAILED level for fine-grained (per-turn) event display

# Plan events
PLAN_CREATED = "soothe.cognition.plan.created"

# Tool events (DEBUG/DETAILED level)
TOOL_STARTED = "soothe.tool.execution.started"
TOOL_COMPLETED = "soothe.tool.execution.completed"
TOOL_ERROR = "soothe.tool.execution.error"

# Agent loop events (DEBUG level; wire ``mode=custom`` types)
STRANGE_LOOP_STARTED = "soothe.cognition.strange_loop.started"
STRANGE_LOOP_ITERATION = "soothe.cognition.strange_loop.iterated"
STRANGE_LOOP_COMPLETED = "soothe.cognition.strange_loop.completed"
STRANGE_LOOP_STEP_STARTED = "soothe.cognition.strange_loop.step.started"
STRANGE_LOOP_STEP_QUEUED = "soothe.cognition.strange_loop.step.queued"
STRANGE_LOOP_STEP_COMPLETED = "soothe.cognition.strange_loop.step.completed"
STRANGE_LOOP_PLAN_DECISION = "soothe.cognition.strange_loop.plan.decision"
STRANGE_LOOP_PLAN_PHASE = "soothe.cognition.strange_loop.plan.phase"
# Wired specialist lifecycle (orphan SubAgent card)
WIRED_SUBAGENT_STARTED = "soothe.cognition.wired_subagent.started"
WIRED_SUBAGENT_COMPLETED = "soothe.cognition.wired_subagent.completed"
WIRED_SUBAGENT_FAILED = "soothe.cognition.wired_subagent.failed"
WIRED_SUBAGENT_CANCELLED = "soothe.cognition.wired_subagent.cancelled"
INTENT_CLASSIFIED = "soothe.cognition.intent.classified"

# Clarification relay events
LOOP_CLARIFICATION_REQUESTED = "soothe.loop.clarification.requested"
LOOP_CLARIFICATION_ANSWERED = "soothe.loop.clarification.answered"
LOOP_CLARIFICATION_DEFERRED = "soothe.loop.clarification.deferred"

# Stream termination
STREAM_END = "soothe.stream.end"

# Message events (DETAILED level)
MESSAGE_RECEIVED = "soothe.protocol.message.received"
MESSAGE_SENT = "soothe.protocol.message.sent"

# Agent loop configuration constants
DEFAULT_STRANGE_LOOP_MAX_ITERATIONS = 10


__all__ = [
    "ErrorEvent",
    "LifecycleEvent",
    "OutputEvent",
    "ProtocolEvent",
    "SootheEvent",
    "SubagentEvent",
    # Event type constants - plan
    "PLAN_CREATED",
    # Tool (DEBUG/DETAILED)
    "TOOL_STARTED",
    "TOOL_COMPLETED",
    "TOOL_ERROR",
    # Agent loop (DEBUG)
    "STRANGE_LOOP_STARTED",
    "STRANGE_LOOP_ITERATION",
    "STRANGE_LOOP_COMPLETED",
    "STRANGE_LOOP_STEP_STARTED",
    "STRANGE_LOOP_STEP_QUEUED",
    "STRANGE_LOOP_STEP_COMPLETED",
    "STRANGE_LOOP_PLAN_DECISION",
    "STRANGE_LOOP_PLAN_PHASE",
    "WIRED_SUBAGENT_STARTED",
    "WIRED_SUBAGENT_COMPLETED",
    "WIRED_SUBAGENT_FAILED",
    "WIRED_SUBAGENT_CANCELLED",
    "INTENT_CLASSIFIED",
    # Clarification relay
    "LOOP_CLARIFICATION_REQUESTED",
    "LOOP_CLARIFICATION_ANSWERED",
    "LOOP_CLARIFICATION_DEFERRED",
    "STREAM_END",
    # Message (DETAILED)
    "MESSAGE_RECEIVED",
    "MESSAGE_SENT",
    # Constants
    "DEFAULT_STRANGE_LOOP_MAX_ITERATIONS",
]
