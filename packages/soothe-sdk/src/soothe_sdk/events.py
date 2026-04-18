"""Base event classes for Soothe events.

This module provides the base event classes that all specific events inherit from.
Module-specific events are defined in their respective modules and registered via
``register_event()``.

RFC-0015: All progress events use 4-segment type strings
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

        Note: This method requires daemon-side implementation.
        For SDK use, events are typically sent via WebSocket.

        SDK-side event base class: provides type definition and serialization.
        Daemon-side implementation in soothe.utils.progress provides actual emit.
        """
        pass


class LifecycleEvent(SootheEvent):
    """Thread and session lifecycle events."""


class ProtocolEvent(SootheEvent):
    """Core protocol activity events."""


class SubagentEvent(SootheEvent):
    """Subagent activity events."""


class OutputEvent(SootheEvent):
    """Content destined for user display."""


class ErrorEvent(SootheEvent):
    """Error events."""

    error: str


# Event type constants (IG-174 Phase 2)
# Wire-safe event type strings for CLI/TUI event processing
# Exposed at DEBUG and DETAILED level for thread-level events display

# Plan events
PLAN_CREATED = "soothe.cognition.plan.created"
PLAN_STEP_STARTED = "soothe.cognition.plan.step.started"
PLAN_STEP_COMPLETED = "soothe.cognition.plan.step.completed"

# Subagent events
SUBAGENT_RESEARCH_INTERNAL_LLM = "soothe.capability.research.internal_llm.run"

# Thread lifecycle events (exposed for DEBUG/DETAILED level)
THREAD_CREATED = "soothe.lifecycle.thread.started"
THREAD_RESUMED = "soothe.lifecycle.thread.resumed"
THREAD_COMPLETED = "soothe.lifecycle.thread.completed"
THREAD_ERROR = "soothe.lifecycle.thread.error"

# Tool events (DEBUG/DETAILED level)
TOOL_STARTED = "soothe.tool.execution.started"
TOOL_COMPLETED = "soothe.tool.execution.completed"
TOOL_ERROR = "soothe.tool.execution.error"

# Agent loop events (DEBUG level)
AGENT_LOOP_STARTED = "soothe.cognition.agent_loop.started"
AGENT_LOOP_ITERATION = "soothe.cognition.agent_loop.iterated"
AGENT_LOOP_COMPLETED = "soothe.cognition.agent_loop.completed"

# Message events (DETAILED level)
MESSAGE_RECEIVED = "soothe.protocol.message.received"
MESSAGE_SENT = "soothe.protocol.message.sent"

# Output events (QUIET level - always visible)
CHITCHAT_RESPONSE = "soothe.output.chitchat.responded"
FINAL_REPORT = "soothe.output.autonomous.final_report.reported"

# Agent loop configuration constants
DEFAULT_AGENT_LOOP_MAX_ITERATIONS = 10


__all__ = [
    "ErrorEvent",
    "LifecycleEvent",
    "OutputEvent",
    "ProtocolEvent",
    "SootheEvent",
    "SubagentEvent",
    # Event type constants - plan
    "PLAN_CREATED",
    "PLAN_STEP_STARTED",
    "PLAN_STEP_COMPLETED",
    # Subagent
    "SUBAGENT_RESEARCH_INTERNAL_LLM",
    # Thread lifecycle (DEBUG/DETAILED)
    "THREAD_CREATED",
    "THREAD_RESUMED",
    "THREAD_COMPLETED",
    "THREAD_ERROR",
    # Tool (DEBUG/DETAILED)
    "TOOL_STARTED",
    "TOOL_COMPLETED",
    "TOOL_ERROR",
    # Agent loop (DEBUG)
    "AGENT_LOOP_STARTED",
    "AGENT_LOOP_ITERATION",
    "AGENT_LOOP_COMPLETED",
    # Message (DETAILED)
    "MESSAGE_RECEIVED",
    "MESSAGE_SENT",
    # Output
    "CHITCHAT_RESPONSE",
    "FINAL_REPORT",
    # Constants
    "DEFAULT_AGENT_LOOP_MAX_ITERATIONS",
]
