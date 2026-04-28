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
    from soothe.core.events import THREAD_CREATED, GOAL_CREATED

    # For type-safe event emission (recommended)
    from soothe.core.events import ThreadCreatedEvent, custom_event
    yield custom_event(ThreadCreatedEvent(thread_id=tid).to_dict())

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
    AgenticStepCompletedEvent,
    AgenticStepStartedEvent,
    AutonomousGoalCompletionEvent,
    CheckpointSavedEvent,
    ChitchatResponseEvent,
    # Output events
    ChitchatStartedEvent,
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
    QuizResponseEvent,
    QuizStartedEvent,
    RecoveryResumedEvent,
    # Type alias
    StreamChunk,
    # Lifecycle events
    ThreadCreatedEvent,
    ThreadEndedEvent,
    ThreadResumedEvent,
    ThreadSavedEvent,
    ThreadStartedEvent,
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
    AGENT_LOOP_STARTED,
    AGENT_LOOP_STEP_COMPLETED,
    AGENT_LOOP_STEP_STARTED,
    AUTONOMOUS_GOAL_COMPLETION,
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
    CHITCHAT_RESPONSE,
    CHITCHAT_STARTED,
    DAEMON_HEARTBEAT,
    ERROR,
    GOAL_BATCH_STARTED,
    GOAL_COMPLETED,
    GOAL_COMPLETION_RESPONDED,
    GOAL_COMPLETION_STREAMING,
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
    QUIZ_RESPONSE,
    QUIZ_STARTED,
    RECOVERY_RESUMED,
    THREAD_CREATED,
    THREAD_ENDED,
    THREAD_RESUMED,
    THREAD_SAVED,
    THREAD_STARTED,
    THREAD_SWITCHED,
)

__all__ = [
    # Verbosity tier (from SDK)
    "VerbosityTier",
    # All event constants (from constants import *)
    "THREAD_CREATED",
    "THREAD_STARTED",
    "THREAD_RESUMED",
    "THREAD_SAVED",
    "THREAD_ENDED",
    "THREAD_SWITCHED",
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
    "CHITCHAT_STARTED",
    "CHITCHAT_RESPONSE",
    "QUIZ_STARTED",
    "QUIZ_RESPONSE",
    "GOAL_COMPLETION_RESPONDED",
    "GOAL_COMPLETION_STREAMING",
    "AUTONOMOUS_GOAL_COMPLETION",
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
    "ThreadCreatedEvent",
    "ThreadStartedEvent",
    "ThreadResumedEvent",
    "ThreadSavedEvent",
    "ThreadEndedEvent",
    "IterationStartedEvent",
    "IterationCompletedEvent",
    "CheckpointSavedEvent",
    "RecoveryResumedEvent",
    "DaemonHeartbeatEvent",
    "AgenticLoopStartedEvent",
    "AgenticLoopCompletedEvent",
    "AgenticStepStartedEvent",
    "AgenticStepCompletedEvent",
    "AutonomousGoalCompletionEvent",
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
    "ChitchatStartedEvent",
    "ChitchatResponseEvent",
    "QuizStartedEvent",
    "QuizResponseEvent",
    # Maker functions
    "make_subagent_tool_started",
    "make_subagent_tool_completed",
    "make_subagent_tool_failed",
]
