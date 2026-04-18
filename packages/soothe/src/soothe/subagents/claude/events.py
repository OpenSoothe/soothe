"""Claude subagent events.

This module defines events for the Claude subagent.
Events are self-registered at module load time.
"""

from __future__ import annotations

from typing import Literal

from pydantic import ConfigDict
from soothe_sdk.events import SubagentEvent


class ClaudeStartedEvent(SubagentEvent):
    """Claude subagent run started (mirrors browser ``started`` for CLI display)."""

    type: Literal["soothe.capability.claude.started"] = "soothe.capability.claude.started"
    task: str = ""
    resume_session_id: str | None = None

    model_config = ConfigDict(extra="allow")


class ClaudeTextEvent(SubagentEvent):
    """Claude text event."""

    type: Literal["soothe.capability.claude.text.running"] = "soothe.capability.claude.text.running"
    text: str = ""

    model_config = ConfigDict(extra="allow")


class ClaudeToolUseEvent(SubagentEvent):
    """Claude tool use event."""

    type: Literal["soothe.capability.claude.tool.running"] = "soothe.capability.claude.tool.running"
    tool: str = ""

    model_config = ConfigDict(extra="allow")


class ClaudeResultEvent(SubagentEvent):
    """Claude result event."""

    type: Literal["soothe.capability.claude.completed"] = "soothe.capability.claude.completed"
    cost_usd: float = 0.0
    duration_ms: int = 0
    claude_session_id: str | None = None

    model_config = ConfigDict(extra="allow")


# Register all Claude events with the global registry
from soothe_sdk.verbosity import VerbosityTier  # noqa: E402

from soothe.core.event_catalog import register_event  # noqa: E402

register_event(
    ClaudeStartedEvent,
    verbosity=VerbosityTier.NORMAL,
    summary_template="Claude: {task}",
)
# IG-089: Claude subagent internal events at DETAILED (hidden at normal)
register_event(
    ClaudeTextEvent,
    verbosity=VerbosityTier.DETAILED,
    summary_template="Text: {text}",
)
register_event(
    ClaudeToolUseEvent,
    verbosity=VerbosityTier.DETAILED,
    summary_template="Tool: {tool}",
)
register_event(
    ClaudeResultEvent,
    verbosity=VerbosityTier.NORMAL,  # Completion visible
    summary_template="Done (${cost_usd}, {duration_ms}ms)",
)

# Event type constants for convenient imports
SUBAGENT_CLAUDE_STARTED = "soothe.capability.claude.started"
SUBAGENT_CLAUDE_TEXT = "soothe.capability.claude.text.running"
SUBAGENT_CLAUDE_TOOL_USE = "soothe.capability.claude.tool.running"
SUBAGENT_CLAUDE_RESULT = "soothe.capability.claude.completed"

__all__ = [
    "SUBAGENT_CLAUDE_RESULT",
    "SUBAGENT_CLAUDE_STARTED",
    "SUBAGENT_CLAUDE_TEXT",
    "SUBAGENT_CLAUDE_TOOL_USE",
    "ClaudeResultEvent",
    "ClaudeStartedEvent",
    "ClaudeTextEvent",
    "ClaudeToolUseEvent",
]
