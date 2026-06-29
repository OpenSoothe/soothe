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
    from soothe.foundation.events import GOAL_CREATED, BRANCH_CREATED

    # For type-safe event emission (recommended)
    from soothe.foundation.events import GoalCreatedEvent, custom_event
    yield custom_event(GoalCreatedEvent(goal_id=gid).to_dict())

    # For event registration
    from soothe.foundation.events import register_event, EventPriority
    register_event(MyCustomEvent, priority=EventPriority.HIGH)

RFC-0015: 4-segment naming convention: soothe.<domain>.<component>.<action>
"""

from __future__ import annotations

# Import VerbosityTier from SDK for backward compatibility
from soothe_sdk.core.verbosity import VerbosityTier

from .catalog import (
    REGISTRY,
    AutopilotModeSwitchedEvent,
    CheckpointSavedEvent,
    DaemonHeartbeatEvent,
    EventMeta,
    EventPriority,
    # Registry classes
    EventRegistry,
    GoalBatchStartedEvent,
    GoalCompletedEvent,
    GoalCreatedEvent,
    GoalDecomposedEvent,
    GoalDeferredEvent,
    GoalDirectivesAppliedEvent,
    GoalFailedEvent,
    GoalRemovedEvent,
    GoalReportEvent,
    IntentClassifiedEvent,  # IG-518
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
    PolicyCheckedEvent,
    PolicyDeniedEvent,
    RecoveryResumedEvent,
    # StrangeLoop events
    StrangeLoopCompletedEvent,
    StrangeLoopContextCompactionEvent,
    StrangeLoopPlanDecisionEvent,
    StrangeLoopStartedEvent,
    StrangeLoopStepCompletedEvent,
    StrangeLoopStepQueuedEvent,
    StrangeLoopStepStartedEvent,
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
    AUTOPILOT_CHECKPOINT_SAVED,
    AUTOPILOT_DREAMING_ENTERED,
    AUTOPILOT_DREAMING_EXITED,
    AUTOPILOT_GOAL_BLOCKED,
    AUTOPILOT_GOAL_COMPLETED,
    AUTOPILOT_GOAL_CREATED,
    AUTOPILOT_GOAL_PROGRESS,
    AUTOPILOT_GOAL_SUSPENDED,
    AUTOPILOT_GOAL_VALIDATED,
    AUTOPILOT_MODE_SWITCHED,
    AUTOPILOT_RELATIONSHIP_DETECTED,
    AUTOPILOT_SEND_BACK,
    AUTOPILOT_STATUS_CHANGED,
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
    GOAL_DECOMPOSED,
    GOAL_DEFERRED,
    GOAL_DIRECTIVES_APPLIED,
    GOAL_FAILED,
    GOAL_REMOVED,
    GOAL_REPORT,
    INTENT_CLASSIFIED,  # IG-518
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
    PLUGIN_FAILED,
    PLUGIN_LOADED,
    PLUGIN_UNLOADED,
    POLICY_CHECKED,
    POLICY_DENIED,
    RECOVERY_RESUMED,
    REPLAY_COMPLETE,
    STRANGE_LOOP_COMPLETED,
    STRANGE_LOOP_CONTEXT_COMPACTED,
    STRANGE_LOOP_PLAN_DECISION,
    STRANGE_LOOP_REASONED,
    STRANGE_LOOP_STARTED,
    STRANGE_LOOP_STEP_COMPLETED,
    STRANGE_LOOP_STEP_STARTED,
)

# Import all event classes, registry, and helpers
from .visibility import (
    event_type_from_wire_message,
    is_client_broadcast_event_type,
    is_progress_wire_event,
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
    "GOAL_CREATED",
    "GOAL_COMPLETED",
    "GOAL_FAILED",
    "GOAL_BATCH_STARTED",
    "GOAL_REPORT",
    "GOAL_DIRECTIVES_APPLIED",
    "GOAL_DEFERRED",
    "INTENT_CLASSIFIED",  # IG-518
    "PLAN_CREATED",
    "PLAN_BATCH_STARTED",
    "PLAN_REFLECTED",
    "PLAN_DAG_SNAPSHOT",
    "STRANGE_LOOP_REASONED",
    "REPLAY_COMPLETE",
    "STRANGE_LOOP_STARTED",
    "STRANGE_LOOP_COMPLETED",
    "STRANGE_LOOP_CONTEXT_COMPACTED",
    "STRANGE_LOOP_PLAN_DECISION",
    "STRANGE_LOOP_STEP_STARTED",
    "STRANGE_LOOP_STEP_QUEUED",
    "STRANGE_LOOP_STEP_COMPLETED",
    "BRANCH_CREATED",
    "BRANCH_ANALYZED",
    "BRANCH_RETRY_STARTED",
    "BRANCH_PRUNED",
    "MEMORY_RECALLED",
    "MEMORY_STORED",
    "POLICY_CHECKED",
    "POLICY_DENIED",
    "DAEMON_HEARTBEAT",
    "AUTOPILOT_STATUS_CHANGED",
    "AUTOPILOT_GOAL_CREATED",
    "AUTOPILOT_GOAL_PROGRESS",
    "AUTOPILOT_GOAL_COMPLETED",
    "AUTOPILOT_DREAMING_ENTERED",
    "AUTOPILOT_DREAMING_EXITED",
    "AUTOPILOT_GOAL_VALIDATED",
    "AUTOPILOT_GOAL_SUSPENDED",
    "AUTOPILOT_SEND_BACK",
    "AUTOPILOT_RELATIONSHIP_DETECTED",
    "AUTOPILOT_CHECKPOINT_SAVED",
    "AUTOPILOT_GOAL_BLOCKED",
    "AUTOPILOT_MODE_SWITCHED",
    "GOAL_DECOMPOSED",
    "GOAL_REMOVED",
    "PLUGIN_LOADED",
    "PLUGIN_FAILED",
    "PLUGIN_UNLOADED",
    "ERROR",
    # Helper functions
    "custom_event",
    "event_type_from_wire_message",
    "is_client_broadcast_event_type",
    "is_progress_wire_event",
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
    # StrangeLoop events
    "StrangeLoopStartedEvent",
    "StrangeLoopCompletedEvent",
    "StrangeLoopPlanDecisionEvent",
    "StrangeLoopStepStartedEvent",
    "StrangeLoopStepQueuedEvent",
    "StrangeLoopStepCompletedEvent",
    "StrangeLoopContextCompactionEvent",
    # Intent events (IG-518)
    "IntentClassifiedEvent",
    # Other events
    "MemoryRecalledEvent",
    "MemoryStoredEvent",
    "PlanCreatedEvent",
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
    "GoalDecomposedEvent",
    "GoalRemovedEvent",
    "AutopilotModeSwitchedEvent",
    # Maker functions
    "make_subagent_tool_started",
    "make_subagent_tool_completed",
    "make_subagent_tool_failed",
]


# Lazy imports for internal bus (kept to avoid circular deps).
def __getattr__(name: str) -> object:
    # RFC-222: Internal EventBus (lazy import to avoid circular deps)
    if name == "InternalEventBus":
        from soothe.foundation.events.internal_bus import InternalEventBus

        return InternalEventBus
    if name == "get_internal_bus":
        from soothe.foundation.events.internal_bus import get_internal_bus

        return get_internal_bus
    if name == "reset_internal_bus":
        from soothe.foundation.events.internal_bus import reset_internal_bus

        return reset_internal_bus
    # RFC-222: Internal event types (lazy import to avoid circular deps)
    if name == "INTERNAL_EVENT_TYPES":
        from soothe.foundation.events.internal_events import INTERNAL_EVENT_TYPES  # noqa: F401

        return INTERNAL_EVENT_TYPES
    if name == "is_internal_event_type":
        from soothe.foundation.events.internal_events import is_internal_event_type

        return is_internal_event_type

    # Internal goal events
    if name == "InternalGoalCompletedEvent":
        from soothe.foundation.events.internal_events import InternalGoalCompletedEvent

        return InternalGoalCompletedEvent
    if name == "InternalGoalFailedEvent":
        from soothe.foundation.events.internal_events import InternalGoalFailedEvent

        return InternalGoalFailedEvent
    if name == "InternalGoalProgressEvent":
        from soothe.foundation.events.internal_events import InternalGoalProgressEvent

        return InternalGoalProgressEvent
    if name == "InternalGoalStateChangedEvent":
        from soothe.foundation.events.internal_events import InternalGoalStateChangedEvent

        return InternalGoalStateChangedEvent
    if name == "InternalGoalsReadyEvent":
        from soothe.foundation.events.internal_events import InternalGoalsReadyEvent

        return InternalGoalsReadyEvent

    # Internal loop events
    if name == "InternalLoopAssignedEvent":
        from soothe.foundation.events.internal_events import InternalLoopAssignedEvent

        return InternalLoopAssignedEvent
    if name == "InternalLoopIdleEvent":
        from soothe.foundation.events.internal_events import InternalLoopIdleEvent

        return InternalLoopIdleEvent
    if name == "InternalLoopReleasedEvent":
        from soothe.foundation.events.internal_events import InternalLoopReleasedEvent

        return InternalLoopReleasedEvent
    if name == "InternalLoopSpawnedEvent":
        from soothe.foundation.events.internal_events import InternalLoopSpawnedEvent

        return InternalLoopSpawnedEvent

    # Internal file events
    if name == "InternalFileLockedEvent":
        from soothe.foundation.events.internal_events import InternalFileLockedEvent

        return InternalFileLockedEvent
    if name == "InternalFileReleasedEvent":
        from soothe.foundation.events.internal_events import InternalFileReleasedEvent

        return InternalFileReleasedEvent
    if name == "InternalFileConflictEvent":
        from soothe.foundation.events.internal_events import InternalFileConflictEvent

        return InternalFileConflictEvent

    # Internal autopilot events
    if name == "InternalAutopilotStartedEvent":
        from soothe.foundation.events.internal_events import InternalAutopilotStartedEvent

        return InternalAutopilotStartedEvent
    if name == "InternalAutopilotStoppedEvent":
        from soothe.foundation.events.internal_events import InternalAutopilotStoppedEvent

        return InternalAutopilotStoppedEvent
    if name == "InternalLoopPoolChangedEvent":
        from soothe.foundation.events.internal_events import InternalLoopPoolChangedEvent

        return InternalLoopPoolChangedEvent
    if name == "InternalAutopilotDreamingEvent":
        from soothe.foundation.events.internal_events import InternalAutopilotDreamingEvent

        return InternalAutopilotDreamingEvent
    if name == "InternalAutopilotAwakeEvent":
        from soothe.foundation.events.internal_events import InternalAutopilotAwakeEvent

        return InternalAutopilotAwakeEvent

    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
