"""Centralized event type string constants for CoreAgent protocol events."""

from __future__ import annotations

MEMORY_RECALLED = "soothe.internal.memory.recalled"
MEMORY_STORED = "soothe.internal.memory.stored"

POLICY_CHECKED = "soothe.internal.policy.checked"
POLICY_DENIED = "soothe.internal.policy.denied"

ERROR = "soothe.error.general.failed"

STREAM_END = "soothe.stream.end"

LLM_RETRY_ATTEMPT = "soothe.cognition.llm.retry.attempt"

MCP_LIST_CHANGED = "soothe.internal.mcp.list_changed"
MCP_TOOL_TIMEOUT = "soothe.internal.mcp.tool.timeout"

PLUGIN_LOADED = "soothe.internal.plugin.loaded"
PLUGIN_FAILED = "soothe.internal.plugin.failed"
PLUGIN_UNLOADED = "soothe.internal.plugin.unloaded"

SKILL_BODY_LOADED = "soothe.internal.skill.body.loaded"

REPLAY_COMPLETE = "replay_complete"

__all__ = [
    "ERROR",
    "LLM_RETRY_ATTEMPT",
    "MCP_LIST_CHANGED",
    "MCP_TOOL_TIMEOUT",
    "MEMORY_RECALLED",
    "MEMORY_STORED",
    "PLUGIN_FAILED",
    "PLUGIN_LOADED",
    "PLUGIN_UNLOADED",
    "POLICY_CHECKED",
    "POLICY_DENIED",
    "REPLAY_COMPLETE",
    "SKILL_BODY_LOADED",
    "STREAM_END",
]
