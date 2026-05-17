"""Event system package - centralized event infrastructure.

This package provides:
- Event type string constants (single source of truth)
- Event model classes (Pydantic models)
- Event registry for O(1) lookup and dispatch
- Helper functions for event emission

Architecture:
- constants.py: Event type string constants
- catalog.py: Event models, registry, registration logic

Usage:
    # For event type constants
    from soothe.core.events import GOAL_CREATED, BRANCH_CREATED

    # For type-safe event emission (recommended)
    from soothe.core.events import GoalCreatedEvent, custom_event
    yield custom_event(GoalCreatedEvent(goal_id=gid).to_dict())

    # For event registration
    from soothe.core.events import register_event, EventPriority
    register_event(MyCustomEvent, priority=EventPriority.HIGH)

RFC-0015: 4-segment naming convention: soothe.<domain>.<component>.<action>
"""

from __future__ import annotations

# Import VerbosityTier from SDK for backward compatibility
from soothe_sdk.core.verbosity import VerbosityTier

# Import all event classes, registry, and helpers
from .catalog import (
    REGISTRY,
    AgenticLoopCompletedEvent,
    # Agentic loop events
    AgenticLoopStartedEvent,
    AgenticPlanDecisionEvent,
    AgenticStepCompletedEvent,
    AgenticStepStartedEvent,
    CheckpointSavedEvent,
    DaemonHeartbeatEvent,
    EventMeta,
    EventPriority,
    # Registry classes
    EventRegistry,
    GoalBatchStartedEvent,
    GoalCompletedEvent,
    GoalCreatedEvent,
    GoalDeferredEvent,
    GoalDirectivesAppliedEvent,
    GoalFailedEvent,
    GoalReportEvent,
    IterationCompletedEvent,
    IterationStartedEvent,
    LoopCompletedEvent,
    LoopCreatedEvent,
    LoopStartedEvent,
    # Protocol events
    MemoryRecalledEvent,
    MemoryStoredEvent,
    PlanBatchStartedEvent,
    PlanCreatedEvent,
    PlanDagSnapshotEvent,
    PlanReflectedEvent,
    PlanStepCompletedEvent,
    PlanStepFailedEvent,
    PlanStepStartedEvent,
    PolicyCheckedEvent,
    PolicyDeniedEvent,
    RecoveryResumedEvent,
    # Type alias
    StreamChunk,
    # Helper functions
    custom_event,
    make_subagent_tool_completed,
    make_subagent_tool_failed,
    # Maker functions
    make_subagent_tool_started,
    register_event,
)

# Import all event type constants
from .constants import (
    AGENT_LOOP_COMPLETED,
    AGENT_LOOP_PLAN_DECISION,
    AGENT_LOOP_STARTED,
    AGENT_LOOP_STEP_COMPLETED,
    AGENT_LOOP_STEP_STARTED,
    AUTOPILLOT_CHECKPOINT_SAVED,
    AUTOPILLOT_DREAMING_ENTERED,
    AUTOPILLOT_DREAMING_EXITED,
    AUTOPILLOT_GOAL_BLOCKED,
    AUTOPILLOT_GOAL_COMPLETED,
    AUTOPILLOT_GOAL_CREATED,
    AUTOPILLOT_GOAL_PROGRESS,
    AUTOPILLOT_GOAL_SUSPENDED,
    AUTOPILLOT_GOAL_VALIDATED,
    AUTOPILLOT_RELATIONSHIP_DETECTED,
    AUTOPILLOT_SEND_BACK,
    AUTOPILLOT_STATUS_CHANGED,
    BRANCH_ANALYZED,
    BRANCH_CREATED,
    BRANCH_PRUNED,
    BRANCH_RETRY_STARTED,
    CHECKPOINT_ANCHOR_CREATED,
    CHECKPOINT_SAVED,
    DAEMON_HEARTBEAT,
    ERROR,
    GOAL_BATCH_STARTED,
    GOAL_COMPLETED,
    GOAL_CREATED,
    GOAL_DEFERRED,
    GOAL_DIRECTIVES_APPLIED,
    GOAL_FAILED,
    GOAL_REPORT,
    HISTORY_REPLAY_COMPLETE,
    ITERATION_COMPLETED,
    ITERATION_STARTED,
    LOOP_COMPLETED,
    LOOP_CREATED,
    LOOP_DETACHED,
    LOOP_REATTACHED,
    LOOP_STARTED,
    MEMORY_RECALLED,
    MEMORY_STORED,
    PLAN_BATCH_STARTED,
    PLAN_CREATED,
    PLAN_DAG_SNAPSHOT,
    PLAN_REFLECTED,
    PLAN_STEP_COMPLETED,
    PLAN_STEP_FAILED,
    PLAN_STEP_STARTED,
    PLUGIN_FAILED,
    PLUGIN_LOADED,
    PLUGIN_UNLOADED,
    POLICY_CHECKED,
    POLICY_DENIED,
    RECOVERY_RESUMED,
)

__all__ = [
    # Verbosity tier (from SDK)
    "VerbosityTier",
    # All event constants (from constants import *)
    "ITERATION_STARTED",
    "ITERATION_COMPLETED",
    "CHECKPOINT_SAVED",
    "CHECKPOINT_ANCHOR_CREATED",
    "RECOVERY_RESUMED",
    "LOOP_CREATED",
    "LOOP_STARTED",
    "LOOP_DETACHED",
    "LOOP_REATTACHED",
    "LOOP_COMPLETED",
    "HISTORY_REPLAY_COMPLETE",
    "GOAL_CREATED",
    "GOAL_COMPLETED",
    "GOAL_FAILED",
    "GOAL_BATCH_STARTED",
    "GOAL_REPORT",
    "GOAL_DIRECTIVES_APPLIED",
    "GOAL_DEFERRED",
    "PLAN_CREATED",
    "PLAN_STEP_STARTED",
    "PLAN_STEP_COMPLETED",
    "PLAN_STEP_FAILED",
    "PLAN_BATCH_STARTED",
    "PLAN_REFLECTED",
    "PLAN_DAG_SNAPSHOT",
    "AGENT_LOOP_STARTED",
    "AGENT_LOOP_COMPLETED",
    "AGENT_LOOP_PLAN_DECISION",
    "AGENT_LOOP_STEP_STARTED",
    "AGENT_LOOP_STEP_COMPLETED",
    "BRANCH_CREATED",
    "BRANCH_ANALYZED",
    "BRANCH_RETRY_STARTED",
    "BRANCH_PRUNED",
    "MEMORY_RECALLED",
    "MEMORY_STORED",
    "POLICY_CHECKED",
    "POLICY_DENIED",
    "DAEMON_HEARTBEAT",
    "AUTOPILLOT_STATUS_CHANGED",
    "AUTOPILLOT_GOAL_CREATED",
    "AUTOPILLOT_GOAL_PROGRESS",
    "AUTOPILLOT_GOAL_COMPLETED",
    "AUTOPILLOT_DREAMING_ENTERED",
    "AUTOPILLOT_DREAMING_EXITED",
    "AUTOPILLOT_GOAL_VALIDATED",
    "AUTOPILLOT_GOAL_SUSPENDED",
    "AUTOPILLOT_SEND_BACK",
    "AUTOPILLOT_RELATIONSHIP_DETECTED",
    "AUTOPILLOT_CHECKPOINT_SAVED",
    "AUTOPILLOT_GOAL_BLOCKED",
    "PLUGIN_LOADED",
    "PLUGIN_FAILED",
    "PLUGIN_UNLOADED",
    "ERROR",
    # Helper functions
    "custom_event",
    # Registry classes
    "EventRegistry",
    "EventMeta",
    "EventPriority",
    "REGISTRY",
    "register_event",
    # Type alias
    "StreamChunk",
    # Event model classes
    "IterationStartedEvent",
    "IterationCompletedEvent",
    "LoopCreatedEvent",
    "LoopStartedEvent",
    "LoopCompletedEvent",
    "CheckpointSavedEvent",
    "RecoveryResumedEvent",
    "DaemonHeartbeatEvent",
    "AgenticLoopStartedEvent",
    "AgenticLoopCompletedEvent",
    "AgenticPlanDecisionEvent",
    "AgenticStepStartedEvent",
    "AgenticStepCompletedEvent",
    "MemoryRecalledEvent",
    "MemoryStoredEvent",
    "PlanCreatedEvent",
    "PlanStepStartedEvent",
    "PlanStepCompletedEvent",
    "PlanStepFailedEvent",
    "PlanBatchStartedEvent",
    "PlanReflectedEvent",
    "PlanDagSnapshotEvent",
    "PolicyCheckedEvent",
    "PolicyDeniedEvent",
    "GoalCreatedEvent",
    "GoalCompletedEvent",
    "GoalFailedEvent",
    "GoalBatchStartedEvent",
    "GoalReportEvent",
    "GoalDirectivesAppliedEvent",
    "GoalDeferredEvent",
    # Maker functions
    "make_subagent_tool_started",
    "make_subagent_tool_completed",
    "make_subagent_tool_failed",
    # Event replay (RFC-411)
    "reconstruct_event_stream",
    "enrich_events_with_coreagent_details",
]


# Lazy imports for replay submodule to avoid circular dependencies
def __getattr__(name: str) -> object:
    if name == "reconstruct_event_stream":
        from soothe.core.events.replay import reconstruct_event_stream

        return reconstruct_event_stream
    if name == "enrich_events_with_coreagent_details":
        from soothe.core.events.replay import enrich_events_with_coreagent_details

        return enrich_events_with_coreagent_details
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
