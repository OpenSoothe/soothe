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
    ConfigReloadedEvent,
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
    StrangeLoopPlanPhaseStatusEvent,
    StrangeLoopStartedEvent,
    StrangeLoopStepCompletedEvent,
    StrangeLoopStepQueuedEvent,
    StrangeLoopStepStartedEvent,
    # Type alias
    StreamChunk,
    WiredSubagentCancelledEvent,
    WiredSubagentCompletedEvent,
    WiredSubagentFailedEvent,
    WiredSubagentStartedEvent,
    # Helper functions
    custom_event,
    register_event,
)

# Import all event type constants
from .constants import (
    AUTOPILOT_CHECKPOINT_SAVED,
    AUTOPILOT_DREAMING_COMPLETED,
    AUTOPILOT_DREAMING_STARTED,
    AUTOPILOT_FEEDBACK_SENT,
    AUTOPILOT_GOAL_BLOCKED,
    AUTOPILOT_GOAL_COMPLETED,
    AUTOPILOT_GOAL_CREATED,
    AUTOPILOT_GOAL_REPORTED,
    AUTOPILOT_GOAL_SUSPENDED,
    AUTOPILOT_GOAL_VALIDATED,
    AUTOPILOT_MODE_SWITCHED,
    AUTOPILOT_RELATIONSHIP_DETECTED,
    AUTOPILOT_STATUS_CHANGED,
    BRANCH_ANALYZED,
    BRANCH_CREATED,
    BRANCH_PRUNED,
    BRANCH_RETRY_STARTED,
    CHECKPOINT_ANCHOR_CREATED,
    CHECKPOINT_SAVED,
    CONFIG_RELOADED,
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
    STRANGE_LOOP_PLAN_PHASE,
    STRANGE_LOOP_REASONED,
    STRANGE_LOOP_STARTED,
    STRANGE_LOOP_STEP_COMPLETED,
    STRANGE_LOOP_STEP_QUEUED,
    STRANGE_LOOP_STEP_STARTED,
    WIRED_SUBAGENT_CANCELLED,
    WIRED_SUBAGENT_COMPLETED,
    WIRED_SUBAGENT_FAILED,
    WIRED_SUBAGENT_STARTED,
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
    "STRANGE_LOOP_PLAN_PHASE",
    "STRANGE_LOOP_STEP_STARTED",
    "STRANGE_LOOP_STEP_QUEUED",
    "STRANGE_LOOP_STEP_COMPLETED",
    "WIRED_SUBAGENT_STARTED",
    "WIRED_SUBAGENT_COMPLETED",
    "WIRED_SUBAGENT_FAILED",
    "WIRED_SUBAGENT_CANCELLED",
    "BRANCH_CREATED",
    "BRANCH_ANALYZED",
    "BRANCH_RETRY_STARTED",
    "BRANCH_PRUNED",
    "MEMORY_RECALLED",
    "MEMORY_STORED",
    "POLICY_CHECKED",
    "POLICY_DENIED",
    "CONFIG_RELOADED",
    "DAEMON_HEARTBEAT",
    "AUTOPILOT_STATUS_CHANGED",
    "AUTOPILOT_GOAL_CREATED",
    "AUTOPILOT_GOAL_REPORTED",
    "AUTOPILOT_GOAL_COMPLETED",
    "AUTOPILOT_DREAMING_STARTED",
    "AUTOPILOT_DREAMING_COMPLETED",
    "AUTOPILOT_GOAL_VALIDATED",
    "AUTOPILOT_GOAL_SUSPENDED",
    "AUTOPILOT_FEEDBACK_SENT",
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
    "ConfigReloadedEvent",
    # StrangeLoop events
    "StrangeLoopStartedEvent",
    "StrangeLoopCompletedEvent",
    "StrangeLoopPlanDecisionEvent",
    "StrangeLoopPlanPhaseStatusEvent",
    "StrangeLoopStepStartedEvent",
    "StrangeLoopStepQueuedEvent",
    "StrangeLoopStepCompletedEvent",
    "StrangeLoopContextCompactionEvent",
    "WiredSubagentStartedEvent",
    "WiredSubagentCompletedEvent",
    "WiredSubagentFailedEvent",
    "WiredSubagentCancelledEvent",
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
]


# Lazy imports for internal bus (kept to avoid circular deps).
def __getattr__(name: str) -> object:
    # RFC-222: Internal EventBus (lazy import to avoid circular deps)
    if name == "InternalEventBus":
        from .internal_bus import InternalEventBus

        return InternalEventBus
    # RFC-222: Internal event types (lazy import to avoid circular deps)
    if name == "INTERNAL_EVENT_TYPES":
        from .internal_events import INTERNAL_EVENT_TYPES  # noqa: F401

        return INTERNAL_EVENT_TYPES
    if name == "is_internal_event_type":
        from .internal_events import is_internal_event_type

        return is_internal_event_type

    # Internal goal events
    if name == "InternalGoalCompletedEvent":
        from .internal_events import InternalGoalCompletedEvent

        return InternalGoalCompletedEvent
    if name == "InternalGoalFailedEvent":
        from .internal_events import InternalGoalFailedEvent

        return InternalGoalFailedEvent
    if name == "InternalGoalProgressEvent":
        from .internal_events import InternalGoalProgressEvent

        return InternalGoalProgressEvent
    if name == "InternalGoalStateChangedEvent":
        from .internal_events import InternalGoalStateChangedEvent

        return InternalGoalStateChangedEvent
    if name == "InternalGoalsReadyEvent":
        from .internal_events import InternalGoalsReadyEvent

        return InternalGoalsReadyEvent

    # Internal loop events
    if name == "InternalLoopAssignedEvent":
        from .internal_events import InternalLoopAssignedEvent

        return InternalLoopAssignedEvent
    if name == "InternalLoopIdleEvent":
        from .internal_events import InternalLoopIdleEvent

        return InternalLoopIdleEvent
    if name == "InternalLoopReleasedEvent":
        from .internal_events import InternalLoopReleasedEvent

        return InternalLoopReleasedEvent
    if name == "InternalLoopSpawnedEvent":
        from .internal_events import InternalLoopSpawnedEvent

        return InternalLoopSpawnedEvent

    # Internal file events
    if name == "InternalFileLockedEvent":
        from .internal_events import InternalFileLockedEvent

        return InternalFileLockedEvent
    if name == "InternalFileReleasedEvent":
        from .internal_events import InternalFileReleasedEvent

        return InternalFileReleasedEvent
    if name == "InternalFileConflictEvent":
        from .internal_events import InternalFileConflictEvent

        return InternalFileConflictEvent

    # Internal autopilot events
    if name == "InternalAutopilotStartedEvent":
        from .internal_events import InternalAutopilotStartedEvent

        return InternalAutopilotStartedEvent
    if name == "InternalAutopilotStoppedEvent":
        from .internal_events import InternalAutopilotStoppedEvent

        return InternalAutopilotStoppedEvent
    if name == "InternalLoopPoolChangedEvent":
        from .internal_events import InternalLoopPoolChangedEvent

        return InternalLoopPoolChangedEvent
    if name == "InternalAutopilotDreamingEvent":
        from .internal_events import InternalAutopilotDreamingEvent

        return InternalAutopilotDreamingEvent
    if name == "InternalAutopilotAwakeEvent":
        from .internal_events import InternalAutopilotAwakeEvent

        return InternalAutopilotAwakeEvent

    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
