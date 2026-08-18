"""UX types and constants for client-side event processing."""

from typing import Final

# Milestone custom event types that clients typically always surface in progress UI
# (pipeline framing).
#
# User-visible **assistant answer text** for the main agent loop is not
# modeled as `soothe.output.*` types. It arrives on the LangGraph ``mode="messages"`` stream
# as loop-tagged AI payloads with a ``phase`` field (see ``soothe_sdk.ux.loop_stream``:
# ``goal_completion``, ``chitchat``, ``autonomous_goal``, intent-hint phases). Optional ancillary
# progress may still use the ``soothe.output.*`` domain for verbosity classification only.
ESSENTIAL_EVENT_TYPES: Final[frozenset[str]] = frozenset(
    {
        # Lifecycle events (always show)
        "soothe.cognition.strange_loop.started",
        "soothe.cognition.strange_loop.completed",
        "soothe.cognition.goal.created",
        "soothe.cognition.goal.completed",
        # Cognition events (milestones)
        "soothe.cognition.plan.created",
        "soothe.cognition.plan.completed",
        # Error events (always show)
        "soothe.error.general.failed",
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
