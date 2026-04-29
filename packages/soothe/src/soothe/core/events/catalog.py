"""Core events and event registry for soothe.* events.

Architecture:
- event_constants.py: Event type string constants (single source of truth)
- event_catalog.py: Event models, registry, registration logic

This module provides:
- Event model classes (Pydantic models)
- Event registry for O(1) lookup and dispatch
- Helper functions for event emission
- Event registration logic

Base event classes are defined in soothe.core.base_events.
Module-specific events (subagents, tools) are defined in their respective modules
and imported here for registry.

**Usage:**

For type-safe event emission (recommended):
    from soothe.core.events import ThreadCreatedEvent, PlanStepStartedEvent
    yield custom_event(ThreadCreatedEvent(thread_id=tid).to_dict())

For event type string constants:
    from soothe.core.events import THREAD_CREATED, PLAN_STEP_STARTED
    # Use constants for comparisons, routing, etc.
    if event_type == THREAD_CREATED:
        ...

RFC-0015: 4-segment naming convention: soothe.<domain>.<component>.<action>
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Literal

from soothe_sdk.core.events import (
    LifecycleEvent,
    ProtocolEvent,
    SootheEvent,
)
from soothe_sdk.core.verbosity import VerbosityTier

# Import ALL event type constants from single source of truth
from .constants import (
    AGENT_LOOP_COMPLETED,
    AGENT_LOOP_STARTED,
    AGENT_LOOP_STEP_COMPLETED,
    AGENT_LOOP_STEP_STARTED,
    # Cognition - AgentLoop
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
    # System - Autopilot
    AUTOPILLOT_STATUS_CHANGED,
    BRANCH_ANALYZED,
    # Cognition - Branch
    BRANCH_CREATED,
    BRANCH_PRUNED,
    BRANCH_RETRY_STARTED,
    CHECKPOINT_SAVED,
    # System - Daemon
    DAEMON_HEARTBEAT,
    GOAL_BATCH_STARTED,
    GOAL_COMPLETED,
    # Cognition - Goal
    GOAL_CREATED,
    GOAL_DEFERRED,
    GOAL_DIRECTIVES_APPLIED,
    GOAL_FAILED,
    GOAL_REPORT,
    ITERATION_COMPLETED,
    # Lifecycle - Iteration
    ITERATION_STARTED,
    MEMORY_RECALLED,
    MEMORY_STORED,
    PLAN_BATCH_STARTED,
    # Cognition - Plan
    PLAN_CREATED,
    PLAN_DAG_SNAPSHOT,
    PLAN_REFLECTED,
    PLAN_STEP_COMPLETED,
    PLAN_STEP_FAILED,
    PLAN_STEP_STARTED,
    POLICY_CHECKED,
    POLICY_DENIED,
    # Lifecycle - Recovery
    RECOVERY_RESUMED,
    # Lifecycle - Thread
    THREAD_CREATED,
    THREAD_ENDED,
    THREAD_RESUMED,
    THREAD_SAVED,
    THREAD_STARTED,
)

# ---------------------------------------------------------------------------
# Type aliases and helpers
# ---------------------------------------------------------------------------

StreamChunk = tuple[tuple[str, ...], str, Any]
"""Deepagents-canonical stream chunk: ``(namespace, mode, data)``."""

STREAM_CHUNK_LEN = 3
MSG_PAIR_LEN = 2


def custom_event(data: dict[str, Any]) -> StreamChunk:
    """Build a soothe protocol custom event chunk.

    Args:
        data: Event data dict with 'type' key.

    Returns:
        Stream chunk in deepagents-canonical format.
    """
    return ((), "custom", data)


# ---------------------------------------------------------------------------
# Event type string constants
# All event types follow RFC-0015's 4-segment naming convention:
# ``soothe.<domain>.<component>.<action>``
# Lifecycle events
# ---------------------------------------------------------------------------


class ThreadCreatedEvent(LifecycleEvent):
    type: Literal["soothe.lifecycle.thread.started"] = "soothe.lifecycle.thread.started"
    thread_id: str


class ThreadStartedEvent(LifecycleEvent):
    type: Literal["soothe.lifecycle.thread.started"] = "soothe.lifecycle.thread.started"
    thread_id: str
    protocols: dict[str, Any] = {}  # noqa: RUF012


class ThreadResumedEvent(LifecycleEvent):
    type: Literal["soothe.lifecycle.thread.resumed"] = "soothe.lifecycle.thread.resumed"
    thread_id: str


class ThreadSavedEvent(LifecycleEvent):
    type: Literal["soothe.lifecycle.thread.saved"] = "soothe.lifecycle.thread.saved"
    thread_id: str


class ThreadEndedEvent(LifecycleEvent):
    type: Literal["soothe.lifecycle.thread.ended"] = "soothe.lifecycle.thread.ended"
    thread_id: str


class IterationStartedEvent(LifecycleEvent):
    type: Literal["soothe.lifecycle.iteration.started"] = "soothe.lifecycle.iteration.started"
    iteration: int | str
    goal_id: str = ""
    goal_description: str = ""
    parallel_goals: int = 1


class IterationCompletedEvent(LifecycleEvent):
    type: Literal["soothe.lifecycle.iteration.completed"] = "soothe.lifecycle.iteration.completed"
    iteration: int | str
    goal_id: str = ""
    outcome: str = ""
    duration_ms: int = 0


class CheckpointSavedEvent(LifecycleEvent):
    type: Literal["soothe.lifecycle.checkpoint.saved"] = "soothe.lifecycle.checkpoint.saved"
    thread_id: str
    completed_steps: int = 0
    completed_goals: int = 0


class RecoveryResumedEvent(LifecycleEvent):
    type: Literal["soothe.lifecycle.recovery.resumed"] = "soothe.lifecycle.recovery.resumed"
    thread_id: str
    completed_steps: list[str] = []  # noqa: RUF012
    completed_goals: list[str] = []  # noqa: RUF012
    mode: str = ""


class DaemonHeartbeatEvent(LifecycleEvent):
    """Heartbeat event broadcast by daemon to keep clients alive during long operations.

    RFC-0013: Daemon broadcasts heartbeat every 5 seconds to subscribed clients.
    This prevents client timeout when LLM operations take longer than the client's
    query start timeout (default 20 seconds).
    """

    type: Literal["soothe.system.daemon.heartbeat"] = "soothe.system.daemon.heartbeat"
    thread_id: str = ""
    timestamp: str = ""  # ISO format timestamp
    state: str = "running"  # "running" | "idle"


# ---------------------------------------------------------------------------
# Agentic loop events (RFC-0008)
# ---------------------------------------------------------------------------


class AgenticLoopStartedEvent(LifecycleEvent):
    type: Literal["soothe.cognition.agent_loop.started"] = "soothe.cognition.agent_loop.started"
    thread_id: str
    goal: str
    max_iterations: int
    friendly_message: str | None = None  # IG-287: User-friendly task reinterpretation


class AgenticLoopCompletedEvent(LifecycleEvent):
    type: Literal["soothe.cognition.agent_loop.completed"] = "soothe.cognition.agent_loop.completed"
    thread_id: str
    status: str
    goal_progress: float
    evidence_summary: str
    # IG-267: Include goal for CLI display trophy message
    goal: str = ""
    # One-line UI summary for TUI/registry (avoid duplicating streamed full_output).
    completion_summary: str = ""
    # Layer-2 act steps completed in this thread (for goal-done line when pipeline has 0).
    total_steps: int = 0


class AgenticStepStartedEvent(LifecycleEvent):
    """Level 2: Step description in three-level tree (RFC-0020)."""

    type: Literal["soothe.cognition.agent_loop.step.started"] = (
        "soothe.cognition.agent_loop.step.started"
    )
    step_id: str
    description: str


class AgenticStepCompletedEvent(LifecycleEvent):
    """Level 3: Step result in three-level tree (RFC-0020)."""

    type: Literal["soothe.cognition.agent_loop.step.completed"] = (
        "soothe.cognition.agent_loop.step.completed"
    )
    step_id: str
    success: bool
    summary: str
    duration_ms: int
    tool_call_count: int = 0


# ---------------------------------------------------------------------------
# Protocol events
# ---------------------------------------------------------------------------


class MemoryRecalledEvent(ProtocolEvent):
    type: Literal["soothe.protocol.memory.recalled"] = "soothe.protocol.memory.recalled"
    count: int = 0
    query: str = ""


class MemoryStoredEvent(ProtocolEvent):
    type: Literal["soothe.protocol.memory.stored"] = "soothe.protocol.memory.stored"
    id: str = ""
    source_thread: str = ""


class PlanCreatedEvent(ProtocolEvent):
    type: Literal["soothe.cognition.plan.created"] = "soothe.cognition.plan.created"
    plan_id: str = ""
    goal: str = ""
    steps: list[dict[str, Any]] = []  # noqa: RUF012
    reasoning: str | None = None
    is_plan_only: bool = False


class PlanStepStartedEvent(ProtocolEvent):
    type: Literal["soothe.cognition.plan.step.started"] = "soothe.cognition.plan.step.started"
    step_id: str = ""
    description: str = ""
    depends_on: list[str] = []  # noqa: RUF012
    batch_index: int | None = None
    index: int | None = None


class PlanStepCompletedEvent(ProtocolEvent):
    type: Literal["soothe.cognition.plan.step.completed"] = "soothe.cognition.plan.step.completed"
    step_id: str = ""
    success: bool = False
    result_preview: str | None = None
    duration_ms: int | None = None
    index: int | None = None


class PlanStepFailedEvent(ProtocolEvent):
    type: Literal["soothe.cognition.plan.step.failed"] = "soothe.cognition.plan.step.failed"
    step_id: str = ""
    error: str = ""
    blocked_steps: list[str] | None = None
    duration_ms: int | None = None


class PlanBatchStartedEvent(ProtocolEvent):
    type: Literal["soothe.cognition.plan.batch.started"] = "soothe.cognition.plan.batch.started"
    batch_index: int = 0
    step_ids: list[str] = []  # noqa: RUF012
    parallel_count: int = 1


class PlanReflectedEvent(ProtocolEvent):
    type: Literal["soothe.cognition.plan.reflected"] = "soothe.cognition.plan.reflected"
    should_revise: bool = False
    assessment: str = ""


class PlanDagSnapshotEvent(ProtocolEvent):
    type: Literal["soothe.cognition.plan.dag_snapshot"] = "soothe.cognition.plan.dag_snapshot"
    steps: list[dict[str, Any]] = []  # noqa: RUF012


class PolicyCheckedEvent(ProtocolEvent):
    type: Literal["soothe.protocol.policy.checked"] = "soothe.protocol.policy.checked"
    action: str = ""
    verdict: str = ""
    profile: str | None = None


class PolicyDeniedEvent(ProtocolEvent):
    type: Literal["soothe.protocol.policy.denied"] = "soothe.protocol.policy.denied"
    action: str = ""
    reason: str = ""
    profile: str | None = None


class GoalCreatedEvent(ProtocolEvent):
    type: Literal["soothe.cognition.goal.created"] = "soothe.cognition.goal.created"
    goal_id: str = ""
    description: str = ""
    priority: int | str = ""
    friendly_message: str | None = None  # IG-287: User-friendly task reinterpretation


class GoalCompletedEvent(ProtocolEvent):
    type: Literal["soothe.cognition.goal.completed"] = "soothe.cognition.goal.completed"
    goal_id: str = ""


class GoalFailedEvent(ProtocolEvent):
    type: Literal["soothe.cognition.goal.failed"] = "soothe.cognition.goal.failed"
    goal_id: str = ""
    error: str = ""
    retry_count: int = 0


class GoalBatchStartedEvent(ProtocolEvent):
    type: Literal["soothe.cognition.goal.batch.started"] = "soothe.cognition.goal.batch.started"
    goal_ids: list[str] = []  # noqa: RUF012
    parallel_count: int = 1


class GoalReportEvent(ProtocolEvent):
    type: Literal["soothe.cognition.goal.reported"] = "soothe.cognition.goal.reported"
    goal_id: str = ""
    step_count: int = 0
    completed: int = 0
    failed: int = 0
    summary: str = ""


class GoalDirectivesAppliedEvent(ProtocolEvent):
    type: Literal["soothe.cognition.goal.directives.applied"] = (
        "soothe.cognition.goal.directives.applied"
    )
    goal_id: str = ""
    directives_count: int = 0
    changes: list[Any] = []  # noqa: RUF012


class GoalDeferredEvent(ProtocolEvent):
    type: Literal["soothe.cognition.goal.deferred"] = "soothe.cognition.goal.deferred"
    goal_id: str = ""
    reason: str = ""
    plan_preserved: bool = False


# ---------------------------------------------------------------------------
# Subagent tool events (generic for any subagent)
# ---------------------------------------------------------------------------


def make_subagent_tool_started(agent: str, **extra: Any) -> dict[str, Any]:
    """Build a subagent tool-started event dict."""
    return {"type": f"soothe.subagent.{agent}.tool_started", **extra}


def make_subagent_tool_completed(agent: str, **extra: Any) -> dict[str, Any]:
    """Build a subagent tool-completed event dict."""
    return {"type": f"soothe.subagent.{agent}.tool_completed", **extra}


def make_subagent_tool_failed(agent: str, **extra: Any) -> dict[str, Any]:
    """Build a subagent tool-failed event dict."""
    return {"type": f"soothe.subagent.{agent}.tool_failed", **extra}


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

EventHandler = Any  # Callable[[dict[str, Any]], None]


class EventPriority(Enum):
    """Event priority levels for queue overflow management (IG-258).

    Higher priority events are processed first and less likely to be dropped
    when queues are near capacity.

    Priority levels:
    - CRITICAL: Never dropped, block if queue full (errors, cancellation)
    - HIGH: Rarely dropped (tool results, subagent output)
    - NORMAL: Standard priority (heartbeat, status updates)
    - LOW: First to drop under pressure (debug, trace events)
    """

    CRITICAL = 0  # Never drop, block if necessary
    HIGH = 1  # Rarely drop (tool/subagent results)
    NORMAL = 2  # Standard priority (heartbeat, status)
    LOW = 3  # First to drop (debug/trace)


@dataclass(frozen=True)
class EventMeta:
    """Metadata for a registered event type."""

    type_string: str
    model: type[SootheEvent]
    domain: str
    component: str
    action: str
    verbosity: VerbosityTier
    summary_template: str = ""
    priority: EventPriority = EventPriority.NORMAL  # IG-258


_DOMAIN_DEFAULT_TIER: dict[str, VerbosityTier] = {
    "lifecycle": VerbosityTier.DETAILED,
    "protocol": VerbosityTier.DETAILED,
    "cognition": VerbosityTier.NORMAL,
    "tool": VerbosityTier.INTERNAL,  # RFC-0020: tool display via LangChain on_tool_call
    "subagent": VerbosityTier.DETAILED,  # IG-089: subagent internals hidden at normal
    "output": VerbosityTier.QUIET,
    "error": VerbosityTier.QUIET,
    "agentic": VerbosityTier.NORMAL,
}


@dataclass
class EventRegistry:
    """Central registry for all Soothe event types.

    Provides O(1) lookup by event type string, structural domain
    classification, verbosity resolution, and handler dispatch.
    """

    _by_type: dict[str, EventMeta] = field(default_factory=dict)
    _handlers: dict[str, list[EventHandler]] = field(default_factory=dict)

    def register(self, meta: EventMeta) -> None:
        """Register an event type with its metadata."""
        self._by_type[meta.type_string] = meta

    def get_meta(self, event_type: str) -> EventMeta | None:
        """Look up metadata for an event type string."""
        return self._by_type.get(event_type)

    def classify(self, event_type: str) -> str:
        """Return the domain from an event type string via ``split('.')[1]``."""
        segments = event_type.split(".")
        _min_segments = 2
        return segments[1] if len(segments) >= _min_segments else "unknown"

    def get_verbosity(self, event_type: str) -> VerbosityTier:
        """Return the VerbosityTier for an event type."""
        meta = self._by_type.get(event_type)
        if meta:
            return meta.verbosity
        domain = self.classify(event_type)
        return _DOMAIN_DEFAULT_TIER.get(domain, VerbosityTier.DEBUG)

    def on(self, event_type: str, handler: EventHandler) -> None:
        """Register a handler for an event type (or ``*`` for fallback)."""
        self._handlers.setdefault(event_type, []).append(handler)

    def dispatch(self, event: dict[str, Any]) -> None:
        """Dispatch an event dict to registered handlers."""
        etype = event.get("type", "")
        handlers = self._handlers.get(etype)
        if handlers:
            for h in handlers:
                h(event)
        elif "*" in self._handlers:
            for h in self._handlers["*"]:
                h(event)


REGISTRY = EventRegistry()


def _reg(
    type_string: str,
    model: type[SootheEvent],
    verbosity: VerbosityTier | None = None,
    summary_template: str = "",
    priority: EventPriority = EventPriority.NORMAL,
) -> None:
    """Internal helper for registering core events.

    Args:
        type_string: Event type string (e.g., "soothe.lifecycle.thread.started").
        model: Event model class.
        verbosity: Optional VerbosityTier override.
        summary_template: Optional template for event summaries.
        priority: Event priority for queue overflow management (IG-258).
    """
    parts = type_string.split(".")
    domain = parts[1] if len(parts) >= 2 else "unknown"
    component = parts[2] if len(parts) >= 3 else ""
    action = parts[3] if len(parts) >= 4 else ""
    # Use explicit verbosity if provided (including QUIET=0), otherwise domain default
    v = (
        verbosity
        if verbosity is not None
        else _DOMAIN_DEFAULT_TIER.get(domain, VerbosityTier.DEBUG)
    )
    REGISTRY.register(
        EventMeta(
            type_string=type_string,
            model=model,
            domain=domain,
            component=component,
            action=action,
            verbosity=v,
            summary_template=summary_template,
            priority=priority,
        )
    )


def register_event(
    event_class: type[SootheEvent],
    verbosity: VerbosityTier | None = None,
    summary_template: str = "",
    priority: EventPriority = EventPriority.NORMAL,
) -> None:
    """Register an event class with the global event registry.

    This is the public API for registering events from modules and plugins.
    It auto-extracts the type string from the event class's Pydantic model
    and sets appropriate defaults based on the event's domain.

    **Usage**:

    ```python
    from soothe.core.events import register_event, EventPriority
    from soothe_sdk.events import SootheEvent


    class MyCustomEvent(SootheEvent):
        type: str = "soothe.plugin.custom.event"
        data: str


    # Register the event with custom priority (IG-258)
    register_event(
        MyCustomEvent,
        verbosity="tool_activity",
        summary_template="Custom event: {data}",
        priority=EventPriority.HIGH,  # Less likely to be dropped
    )
    ```

    Args:
        event_class: Event class to register (must have 'type' field with default value).
        verbosity: Optional verbosity category. If not provided, inferred from domain.
        summary_template: Optional template for event summaries (supports field interpolation).
        priority: Event priority for queue overflow management (IG-258). Default: NORMAL.

    Raises:
        KeyError: If event class doesn't have 'type' field with default value.
    """
    # Extract type string from Pydantic model field
    if "type" not in event_class.model_fields:
        msg = f"Event class {event_class.__name__} must have a 'type' field with a default value"
        raise KeyError(msg)

    type_field = event_class.model_fields["type"]
    type_string = type_field.default

    if not isinstance(type_string, str):
        msg = f"Event class {event_class.__name__} 'type' field must have a string default value"
        raise KeyError(msg)

    # Use internal _reg helper for actual registration
    _reg(
        type_string,
        event_class,
        verbosity=verbosity,
        summary_template=summary_template,
        priority=priority,
    )


# -- Lifecycle ---------------------------------------------------------------
_reg(THREAD_CREATED, ThreadCreatedEvent, summary_template="Thread {thread_id} created")
_reg(THREAD_STARTED, ThreadStartedEvent, summary_template="thread={thread_id}")
_reg(THREAD_RESUMED, ThreadResumedEvent, summary_template="Resumed thread: {thread_id}")
_reg(THREAD_SAVED, ThreadSavedEvent, summary_template="Saved thread: {thread_id}")
_reg(THREAD_ENDED, ThreadEndedEvent, summary_template="thread={thread_id}")
_reg(
    ITERATION_STARTED,
    IterationStartedEvent,
    summary_template="iteration {iteration}: {goal_description}",
)
_reg(
    ITERATION_COMPLETED,
    IterationCompletedEvent,
    summary_template="iteration {iteration}: {outcome} ({duration_ms}ms)",
)
_reg(
    CHECKPOINT_SAVED,
    CheckpointSavedEvent,
    summary_template="Checkpoint saved: {completed_steps} steps, {completed_goals} goals",
)
_reg(
    RECOVERY_RESUMED,
    RecoveryResumedEvent,
    summary_template="Recovery resumed: mode={mode}",
)
_reg(
    DAEMON_HEARTBEAT,
    DaemonHeartbeatEvent,
    verbosity=VerbosityTier.DEBUG,
    summary_template="Daemon heartbeat: state={state}",
)

# -- Agentic Loop (RFC-0008) -------------------------------------------------
_reg(
    AGENT_LOOP_STARTED,
    AgenticLoopStartedEvent,
    verbosity=VerbosityTier.NORMAL,
    summary_template="{goal}",
)
_reg(
    AGENT_LOOP_COMPLETED,
    AgenticLoopCompletedEvent,
    verbosity=VerbosityTier.QUIET,
    summary_template="Done: {completion_summary}",
)
_reg(
    AGENT_LOOP_STEP_STARTED,
    AgenticStepStartedEvent,
    verbosity=VerbosityTier.NORMAL,  # RFC-0020: Step descriptions visible at normal verbosity
    summary_template="{description}",
)
_reg(
    AGENT_LOOP_STEP_COMPLETED,
    AgenticStepCompletedEvent,
    verbosity=VerbosityTier.NORMAL,  # Show step completion at normal verbosity for progress visibility
    summary_template="{summary} ({duration_ms}ms)",
)

# -- Protocol: memory --------------------------------------------------------
_reg(MEMORY_RECALLED, MemoryRecalledEvent, summary_template="{count} items recalled")
_reg(MEMORY_STORED, MemoryStoredEvent, summary_template="Stored memory: {id}")

# -- Protocol: plan ----------------------------------------------------------
# Plan display is handled by on_plan_created() renderer, not summary template
_reg(PLAN_CREATED, PlanCreatedEvent)
_reg(PLAN_STEP_STARTED, PlanStepStartedEvent, summary_template="Step {step_id}: {description}")
_reg(
    PLAN_STEP_COMPLETED,
    PlanStepCompletedEvent,
    verbosity=VerbosityTier.DETAILED,
    summary_template="Step {step_id}: done",
)
_reg(PLAN_STEP_FAILED, PlanStepFailedEvent, summary_template="Step {step_id}: FAILED - {error}")
_reg(
    PLAN_BATCH_STARTED,
    PlanBatchStartedEvent,
    summary_template="Batch: {parallel_count} steps in parallel",
)
_reg(PLAN_REFLECTED, PlanReflectedEvent, summary_template="Reflected: {assessment}")
_reg(PLAN_DAG_SNAPSHOT, PlanDagSnapshotEvent, verbosity=VerbosityTier.DEBUG)

# -- Protocol: policy --------------------------------------------------------
_reg(POLICY_CHECKED, PolicyCheckedEvent, summary_template="Policy: {verdict}")
_reg(POLICY_DENIED, PolicyDeniedEvent, summary_template="Denied: {reason}")

# -- Protocol: goal ----------------------------------------------------------
_reg(GOAL_CREATED, GoalCreatedEvent, summary_template="Goal: {description} (priority={priority})")
_reg(GOAL_COMPLETED, GoalCompletedEvent, summary_template="Goal {goal_id} completed")
_reg(GOAL_FAILED, GoalFailedEvent, summary_template="Goal {goal_id} failed (retry {retry_count})")
_reg(
    GOAL_BATCH_STARTED,
    GoalBatchStartedEvent,
    summary_template="Goals: {parallel_count} running in parallel",
)
_reg(
    GOAL_REPORT,
    GoalReportEvent,
    summary_template="[goal] {goal_id}: {completed}/{step_count} steps",
)
_reg(
    GOAL_DIRECTIVES_APPLIED,
    GoalDirectivesAppliedEvent,
    summary_template="Directives applied: {directives_count} changes",
)
_reg(GOAL_DEFERRED, GoalDeferredEvent, summary_template="Goal {goal_id} deferred: {reason}")

# -- Autopilot (RFC-204) -------------------------------------------------


class _BranchCreatedEvent(SootheEvent):
    type: str = "soothe.cognition.branch.created"
    branch_id: str
    iteration: int
    failure_reason: str


class _BranchAnalyzedEvent(SootheEvent):
    type: str = "soothe.cognition.branch.analyzed"
    branch_id: str
    avoid_patterns: list[str] = []
    suggested_adjustments: list[str] = []


class _BranchRetryStartedEvent(SootheEvent):
    type: str = "soothe.cognition.branch.retry.started"
    branch_id: str
    retry_iteration: int
    learning_applied: list[str] = []


class _BranchPrunedEvent(SootheEvent):
    type: str = "soothe.cognition.branch.pruned"
    branch_id: str
    loop_id: str


_reg(BRANCH_CREATED, _BranchCreatedEvent, verbosity=VerbosityTier.NORMAL)
_reg(BRANCH_ANALYZED, _BranchAnalyzedEvent, verbosity=VerbosityTier.DETAILED)
_reg(BRANCH_RETRY_STARTED, _BranchRetryStartedEvent, verbosity=VerbosityTier.NORMAL)
_reg(BRANCH_PRUNED, _BranchPrunedEvent, verbosity=VerbosityTier.DETAILED)


class _AutopilotStatusChanged(SootheEvent):
    type: str = "soothe.system.autopilot.status.changed"
    state: str


class _AutopilotGoalCreated(SootheEvent):
    type: str = "soothe.system.autopilot.goal.created"
    goal_id: str
    description: str = ""


class _AutopilotGoalProgress(SootheEvent):
    type: str = "soothe.system.autopilot.goal.reported"
    goal_id: str
    status: str = ""


class _AutopilotGoalCompleted(SootheEvent):
    type: str = "soothe.system.autopilot.goal.completed"
    goal_id: str


class _AutopilotDreamingEntered(SootheEvent):
    type: str = "soothe.system.autopilot.dreaming.started"
    timestamp: str = ""


class _AutopilotDreamingExited(SootheEvent):
    type: str = "soothe.system.autopilot.dreaming.completed"
    timestamp: str = ""
    trigger: str = ""


class _AutopilotGoalValidated(SootheEvent):
    type: str = "soothe.system.autopilot.goal.validated"
    goal_id: str
    confidence: float = 1.0


class _AutopilotGoalSuspended(SootheEvent):
    type: str = "soothe.system.autopilot.goal.suspended"
    goal_id: str
    reason: str = ""


class _AutopilotSendBack(SootheEvent):
    type: str = "soothe.system.autopilot.feedback.sent"
    goal_id: str
    remaining_budget: int = 0
    feedback: str = ""


class _AutopilotRelationshipDetected(SootheEvent):
    type: str = "soothe.system.autopilot.relationship.detected"
    from_goal: str
    to_goal: str
    relationship_type: str
    confidence: float = 0.0


class _AutopilotCheckpointSaved(SootheEvent):
    type: str = "soothe.system.autopilot.checkpoint.saved"
    thread_id: str
    trigger: str = ""


class _AutopilotGoalBlocked(SootheEvent):
    type: str = "soothe.system.autopilot.goal.blocked"
    goal_id: str
    reason: str = ""


_reg(AUTOPILLOT_STATUS_CHANGED, _AutopilotStatusChanged, verbosity=VerbosityTier.NORMAL)
_reg(AUTOPILLOT_GOAL_CREATED, _AutopilotGoalCreated, verbosity=VerbosityTier.NORMAL)
_reg(AUTOPILLOT_GOAL_PROGRESS, _AutopilotGoalProgress, verbosity=VerbosityTier.NORMAL)
_reg(AUTOPILLOT_GOAL_COMPLETED, _AutopilotGoalCompleted, verbosity=VerbosityTier.NORMAL)
_reg(AUTOPILLOT_DREAMING_ENTERED, _AutopilotDreamingEntered, verbosity=VerbosityTier.NORMAL)
_reg(AUTOPILLOT_DREAMING_EXITED, _AutopilotDreamingExited, verbosity=VerbosityTier.NORMAL)
_reg(AUTOPILLOT_GOAL_VALIDATED, _AutopilotGoalValidated, verbosity=VerbosityTier.DETAILED)
_reg(AUTOPILLOT_GOAL_SUSPENDED, _AutopilotGoalSuspended, verbosity=VerbosityTier.NORMAL)
_reg(AUTOPILLOT_SEND_BACK, _AutopilotSendBack, verbosity=VerbosityTier.DETAILED)
_reg(
    AUTOPILLOT_RELATIONSHIP_DETECTED,
    _AutopilotRelationshipDetected,
    verbosity=VerbosityTier.DETAILED,
)
_reg(AUTOPILLOT_CHECKPOINT_SAVED, _AutopilotCheckpointSaved, verbosity=VerbosityTier.DETAILED)
_reg(AUTOPILLOT_GOAL_BLOCKED, _AutopilotGoalBlocked, verbosity=VerbosityTier.NORMAL)


# ---------------------------------------------------------------------------
# Import event modules to trigger self-registration
# These modules call register_event() at import time
# Must be at the end after all core events are registered
# ---------------------------------------------------------------------------
