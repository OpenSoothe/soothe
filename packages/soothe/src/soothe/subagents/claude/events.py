"""Claude subagent wire events (curated ``soothe.subagent.*``, IG-338)."""

from __future__ import annotations

from typing import Literal

from pydantic import ConfigDict
from soothe_sdk.core.events import SubagentEvent
from soothe_sdk.core.subagent_wire import (
    SUBAGENT_CLAUDE_COMPLETED,
    SUBAGENT_CLAUDE_FAILED,
    SUBAGENT_CLAUDE_STARTED,
    SUBAGENT_CLAUDE_STEP_COMPLETED,
)
from soothe_sdk.core.verbosity import VerbosityTier

from soothe.core.events import register_event


class ClaudeStartedEvent(SubagentEvent):
    """Claude subagent run started."""

    type: Literal["soothe.subagent.claude.started"] = SUBAGENT_CLAUDE_STARTED  # type: ignore[assignment]
    task_preview: str = ""

    model_config = ConfigDict(extra="allow")


class ClaudeStepCompletedEvent(SubagentEvent):
    """One Claude Code tool use completed (metadata for TUI Task card, IG-344)."""

    type: Literal["soothe.subagent.claude.step.completed"] = SUBAGENT_CLAUDE_STEP_COMPLETED  # type: ignore[assignment]
    tool_name: str = ""
    input_preview: str = ""

    model_config = ConfigDict(extra="allow")


class ClaudeCompletedEvent(SubagentEvent):
    """Claude subagent finished successfully."""

    type: Literal["soothe.subagent.claude.completed"] = SUBAGENT_CLAUDE_COMPLETED  # type: ignore[assignment]
    cost_usd: float = 0.0
    duration_ms: int = 0
    claude_session_id: str | None = None
    summary: str = ""

    model_config = ConfigDict(extra="allow")


class ClaudeFailedEvent(SubagentEvent):
    """Claude subagent failed."""

    type: Literal["soothe.subagent.claude.failed"] = SUBAGENT_CLAUDE_FAILED  # type: ignore[assignment]
    message: str = ""

    model_config = ConfigDict(extra="allow")


register_event(
    ClaudeStartedEvent,
    verbosity=VerbosityTier.NORMAL,
    summary_template="Claude: {task_preview}",
)
register_event(
    ClaudeStepCompletedEvent,
    verbosity=VerbosityTier.NORMAL,
    summary_template="{tool_name}: {input_preview}",
)
register_event(
    ClaudeCompletedEvent,
    verbosity=VerbosityTier.NORMAL,
    summary_template="Claude done (${cost_usd}, {duration_ms}ms)",
)
register_event(
    ClaudeFailedEvent,
    verbosity=VerbosityTier.NORMAL,
    summary_template="Claude failed: {message}",
)

__all__ = [
    "SUBAGENT_CLAUDE_COMPLETED",
    "SUBAGENT_CLAUDE_FAILED",
    "SUBAGENT_CLAUDE_STARTED",
    "SUBAGENT_CLAUDE_STEP_COMPLETED",
    "ClaudeCompletedEvent",
    "ClaudeFailedEvent",
    "ClaudeStartedEvent",
    "ClaudeStepCompletedEvent",
]
