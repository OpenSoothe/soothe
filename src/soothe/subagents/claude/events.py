"""Claude subagent events."""

from __future__ import annotations

from typing import Literal

from pydantic import ConfigDict

from soothe.core.base_events import SubagentEvent


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


__all__ = ["ClaudeResultEvent", "ClaudeTextEvent", "ClaudeToolUseEvent"]
