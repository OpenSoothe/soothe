"""Claude subagent events.

This module defines events for the Claude subagent.
Events are self-registered at module load time.
"""

from __future__ import annotations

from typing import Literal

from pydantic import ConfigDict

from soothe.core.base_events import SubagentEvent


class ClaudeDispatchedEvent(SubagentEvent):
    """Claude subagent dispatched event."""

    type: Literal["soothe.subagent.claude.dispatched"] = "soothe.subagent.claude.dispatched"
    task: str = ""

    model_config = ConfigDict(extra="allow")


class ClaudeCompletedEvent(SubagentEvent):
    """Claude subagent completed event."""

    type: Literal["soothe.subagent.claude.completed"] = "soothe.subagent.claude.completed"
    duration_ms: int = 0
    cost_usd: float = 0.0

    model_config = ConfigDict(extra="allow")


class ClaudeTextEvent(SubagentEvent):
    """Claude text event."""

    type: Literal["soothe.subagent.claude.text"] = "soothe.subagent.claude.text"
    text: str = ""

    model_config = ConfigDict(extra="allow")


class ClaudeToolUseEvent(SubagentEvent):
    """Claude tool use event."""

    type: Literal["soothe.subagent.claude.tool_use"] = "soothe.subagent.claude.tool_use"
    tool: str = ""

    model_config = ConfigDict(extra="allow")


class ClaudeResultEvent(SubagentEvent):
    """Claude result event."""

    type: Literal["soothe.subagent.claude.result"] = "soothe.subagent.claude.result"
    cost_usd: float = 0.0
    duration_ms: int = 0

    model_config = ConfigDict(extra="allow")


# Register all Claude events with the global registry
from soothe.core.event_catalog import register_event  # noqa: E402
from soothe.core.verbosity_tier import VerbosityTier  # noqa: E402

register_event(
    ClaudeDispatchedEvent,
    verbosity=VerbosityTier.NORMAL,
    summary_template="Claude: {task}",
)
register_event(
    ClaudeCompletedEvent,
    verbosity=VerbosityTier.NORMAL,
    summary_template="Completed (${cost_usd}, {duration_ms}ms)",
)
register_event(
    ClaudeTextEvent,
    verbosity=VerbosityTier.DETAILED,
    summary_template="Text: {text}",
)
register_event(
    ClaudeToolUseEvent,
    verbosity=VerbosityTier.NORMAL,
    summary_template="Tool: {tool}",
)
register_event(
    ClaudeResultEvent,
    verbosity=VerbosityTier.DETAILED,
    summary_template="Done (${cost_usd}, {duration_ms}ms)",
)

# Event type constants for convenient imports
SUBAGENT_CLAUDE_DISPATCHED = "soothe.subagent.claude.dispatched"
SUBAGENT_CLAUDE_COMPLETED = "soothe.subagent.claude.completed"
SUBAGENT_CLAUDE_TEXT = "soothe.subagent.claude.text"
SUBAGENT_CLAUDE_TOOL_USE = "soothe.subagent.claude.tool_use"
SUBAGENT_CLAUDE_RESULT = "soothe.subagent.claude.result"

__all__ = [
    "SUBAGENT_CLAUDE_COMPLETED",
    "SUBAGENT_CLAUDE_DISPATCHED",
    "SUBAGENT_CLAUDE_RESULT",
    "SUBAGENT_CLAUDE_TEXT",
    "SUBAGENT_CLAUDE_TOOL_USE",
    "ClaudeCompletedEvent",
    "ClaudeDispatchedEvent",
    "ClaudeResultEvent",
    "ClaudeTextEvent",
    "ClaudeToolUseEvent",
]
