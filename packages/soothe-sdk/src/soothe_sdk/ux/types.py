"""UX types and constants for client-side event processing."""

from typing import Final

# Milestone custom event types that clients typically always surface in progress UI
# (RFC-501 / legacy RFC-0020 "pipeline" framing).
#
# IG-317 / RFC-614: User-visible **assistant answer text** for the main agent loop is not
# modeled as `soothe.output.*` types. It arrives on the LangGraph ``mode="messages"`` stream
# as loop-tagged AI payloads with a ``phase`` field (see ``soothe_sdk.ux.loop_stream``:
# ``goal_completion``, ``chitchat``, ``quiz``, ``autonomous_goal``). Optional ancillary
# progress may still use the ``soothe.output.*`` domain for verbosity classification only.
ESSENTIAL_EVENT_TYPES: Final[frozenset[str]] = frozenset(
    {
        # Lifecycle events (always show)
        "soothe.lifecycle.thread.started",
        "soothe.lifecycle.thread.completed",
        "soothe.cognition.agent_loop.started",
        "soothe.cognition.agent_loop.completed",
        "soothe.cognition.goal.created",
        "soothe.cognition.goal.completed",
        # Cognition events (milestones)
        "soothe.cognition.plan.created",
        "soothe.cognition.plan.completed",
        "soothe.cognition.plan.step.started",
        "soothe.cognition.plan.step.completed",
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
