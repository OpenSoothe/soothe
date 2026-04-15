"""UX types and constants for client-side event processing."""

from typing import Final

# Essential event types that are always processed (RFC-0020)
# These are the minimum set for user-facing progress display
ESSENTIAL_EVENT_TYPES: Final[frozenset[str]] = frozenset(
    {
        # Lifecycle events (always show)
        "soothe.lifecycle.thread.started",
        "soothe.lifecycle.thread.completed",
        "soothe.lifecycle.agent_loop.started",
        "soothe.lifecycle.agent_loop.completed",
        "soothe.lifecycle.goal.started",
        "soothe.lifecycle.goal.completed",
        # Protocol events (milestones)
        "soothe.protocol.plan.started",
        "soothe.protocol.plan.completed",
        "soothe.protocol.plan.step_started",
        "soothe.protocol.plan.step_completed",
        # Output events (user-facing content)
        "soothe.output.message",
        "soothe.output.report",
        "soothe.output.progress",
        # Error events (always show)
        "soothe.error.general",
        "soothe.error.tool",
        "soothe.error.subagent",
        # Tool/subagent milestones
        "soothe.tool.invocation.started",
        "soothe.tool.invocation.completed",
        "soothe.subagent.invocation.started",
        "soothe.subagent.invocation.completed",
    }
)


__all__ = ["ESSENTIAL_EVENT_TYPES"]
