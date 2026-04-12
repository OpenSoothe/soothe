"""Core events and event registry for soothe.* events.

RFC-0015: All progress events use 4-segment type strings
``soothe.<domain>.<component>.<action>`` with six domains:
lifecycle, protocol, tool, subagent, output, error.

This module provides:
- Core protocol and lifecycle event models
- Event type string constants
- Event registry for O(1) lookup and dispatch
- Helper functions for event emission

Base event classes are defined in soothe.core.base_events.
Module-specific events (subagents, tools) are defined in their respective modules
and imported here for registry.

**Usage:**

For type-safe event emission (recommended):
    from soothe.core.event_catalog import ThreadCreatedEvent, PlanStepStartedEvent
    yield custom_event(ThreadCreatedEvent(thread_id=tid).to_dict())

For event type string constants:
    from soothe.core.event_catalog import THREAD_CREATED, PLAN_STEP_STARTED
    # Use constants for comparisons, routing, etc.
    if event_type == THREAD_CREATED:
        ...
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from soothe.foundation.base_events import (
    LifecycleEvent,
    OutputEvent,
    ProtocolEvent,
    SootheEvent,
)
from soothe.foundation.verbosity_tier import VerbosityTier

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
# ---------------------------------------------------------------------------

# -- Lifecycle events --------------------------------------------------------
THREAD_CREATED = "soothe.lifecycle.thread.created"
THREAD_STARTED = "soothe.lifecycle.thread.started"
THREAD_RESUMED = "soothe.lifecycle.thread.resumed"
THREAD_SAVED = "soothe.lifecycle.thread.saved"
THREAD_ENDED = "soothe.lifecycle.thread.ended"
ITERATION_STARTED = "soothe.lifecycle.iteration.started"
ITERATION_COMPLETED = "soothe.lifecycle.iteration.completed"
CHECKPOINT_SAVED = "soothe.lifecycle.checkpoint.saved"
RECOVERY_RESUMED = "soothe.lifecycle.recovery.resumed"
DAEMON_HEARTBEAT = "soothe.lifecycle.daemon.heartbeat"

# -- Protocol events ---------------------------------------------------------
MEMORY_RECALLED = "soothe.protocol.memory.recalled"
MEMORY_STORED = "soothe.protocol.memory.stored"
PLAN_CREATED = "soothe.cognition.plan.created"
PLAN_STEP_STARTED = "soothe.cognition.plan.step_started"
PLAN_STEP_COMPLETED = "soothe.cognition.plan.step_completed"
PLAN_STEP_FAILED = "soothe.cognition.plan.step_failed"
PLAN_BATCH_STARTED = "soothe.cognition.plan.batch_started"
PLAN_REFLECTED = "soothe.cognition.plan.reflected"
PLAN_DAG_SNAPSHOT = "soothe.cognition.plan.dag_snapshot"
POLICY_CHECKED = "soothe.protocol.policy.checked"
POLICY_DENIED = "soothe.protocol.policy.denied"
GOAL_CREATED = "soothe.cognition.goal.created"
GOAL_COMPLETED = "soothe.cognition.goal.completed"
GOAL_FAILED = "soothe.cognition.goal.failed"
GOAL_BATCH_STARTED = "soothe.cognition.goal.batch_started"
GOAL_REPORT = "soothe.cognition.goal.report"
GOAL_DIRECTIVES_APPLIED = "soothe.cognition.goal.directives_applied"
GOAL_DEFERRED = "soothe.cognition.goal.deferred"

# -- Output events -----------------------------------------------------------
CHITCHAT_STARTED = "soothe.output.chitchat.started"
CHITCHAT_RESPONSE = "soothe.output.chitchat.response"
FINAL_REPORT = "soothe.output.autonomous.final_report"

# -- Error events ------------------------------------------------------------
ERROR = "soothe.error.general"

# -- Plugin events -----------------------------------------------------------
PLUGIN_LOADED = "soothe.plugin.loaded"
PLUGIN_FAILED = "soothe.plugin.failed"
PLUGIN_UNLOADED = "soothe.plugin.unloaded"


# ---------------------------------------------------------------------------
# Core event class definitions
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Lifecycle events
# ---------------------------------------------------------------------------


class ThreadCreatedEvent(LifecycleEvent):
    type: Literal["soothe.lifecycle.thread.created"] = "soothe.lifecycle.thread.created"
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

    type: Literal["soothe.lifecycle.daemon.heartbeat"] = "soothe.lifecycle.daemon.heartbeat"
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


class AgenticLoopCompletedEvent(LifecycleEvent):
    type: Literal["soothe.cognition.agent_loop.completed"] = "soothe.cognition.agent_loop.completed"
    thread_id: str
    status: str
    goal_progress: float
    evidence_summary: str
    # One-line UI summary for TUI/registry (avoid duplicating streamed full_output).
    completion_summary: str = ""
    # Layer-2 act steps completed in this thread (for goal-done line when pipeline has 0).
    total_steps: int = 0
    # Headless CLI: when max_iterations>1, main assistant stdout is suppressed; surface this once at done.
    final_stdout_message: str | None = None


class AgenticStepStartedEvent(LifecycleEvent):
    """Level 2: Step description in three-level tree (RFC-0020)."""

    type: Literal["soothe.agentic.step.started"] = "soothe.agentic.step.started"
    description: str


class AgenticStepCompletedEvent(LifecycleEvent):
    """Level 3: Step result in three-level tree (RFC-0020)."""

    type: Literal["soothe.agentic.step.completed"] = "soothe.agentic.step.completed"
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
    type: Literal["soothe.cognition.plan.step_started"] = "soothe.cognition.plan.step_started"
    step_id: str = ""
    description: str = ""
    depends_on: list[str] = []  # noqa: RUF012
    batch_index: int | None = None
    index: int | None = None


class PlanStepCompletedEvent(ProtocolEvent):
    type: Literal["soothe.cognition.plan.step_completed"] = "soothe.cognition.plan.step_completed"
    step_id: str = ""
    success: bool = False
    result_preview: str | None = None
    duration_ms: int | None = None
    index: int | None = None


class PlanStepFailedEvent(ProtocolEvent):
    type: Literal["soothe.cognition.plan.step_failed"] = "soothe.cognition.plan.step_failed"
    step_id: str = ""
    error: str = ""
    blocked_steps: list[str] | None = None
    duration_ms: int | None = None


class PlanBatchStartedEvent(ProtocolEvent):
    type: Literal["soothe.cognition.plan.batch_started"] = "soothe.cognition.plan.batch_started"
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


class GoalCompletedEvent(ProtocolEvent):
    type: Literal["soothe.cognition.goal.completed"] = "soothe.cognition.goal.completed"
    goal_id: str = ""


class GoalFailedEvent(ProtocolEvent):
    type: Literal["soothe.cognition.goal.failed"] = "soothe.cognition.goal.failed"
    goal_id: str = ""
    error: str = ""
    retry_count: int = 0


class GoalBatchStartedEvent(ProtocolEvent):
    type: Literal["soothe.cognition.goal.batch_started"] = "soothe.cognition.goal.batch_started"
    goal_ids: list[str] = []  # noqa: RUF012
    parallel_count: int = 1


class GoalReportEvent(ProtocolEvent):
    type: Literal["soothe.cognition.goal.report"] = "soothe.cognition.goal.report"
    goal_id: str = ""
    step_count: int = 0
    completed: int = 0
    failed: int = 0
    summary: str = ""


class GoalDirectivesAppliedEvent(ProtocolEvent):
    type: Literal["soothe.cognition.goal.directives_applied"] = "soothe.cognition.goal.directives_applied"
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
# Output events
# ---------------------------------------------------------------------------


class ChitchatStartedEvent(OutputEvent):
    type: Literal["soothe.output.chitchat.started"] = "soothe.output.chitchat.started"
    query: str = ""


class ChitchatResponseEvent(OutputEvent):
    type: Literal["soothe.output.chitchat.response"] = "soothe.output.chitchat.response"
    content: str = ""


class FinalReportEvent(OutputEvent):
    type: Literal["soothe.output.autonomous.final_report"] = "soothe.output.autonomous.final_report"
    goal_id: str = ""
    description: str = ""
    status: str = ""
    summary: str = ""


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

EventHandler = Any  # Callable[[dict[str, Any]], None]


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
) -> None:
    """Internal helper for registering core events.

    Args:
        type_string: Event type string (e.g., "soothe.lifecycle.thread.created").
        model: Event model class.
        verbosity: Optional VerbosityTier override.
        summary_template: Optional template for event summaries.
    """
    parts = type_string.split(".")
    domain = parts[1] if len(parts) >= 2 else "unknown"
    component = parts[2] if len(parts) >= 3 else ""
    action = parts[3] if len(parts) >= 4 else ""
    # Use explicit verbosity if provided (including QUIET=0), otherwise domain default
    v = verbosity if verbosity is not None else _DOMAIN_DEFAULT_TIER.get(domain, VerbosityTier.DEBUG)
    REGISTRY.register(
        EventMeta(
            type_string=type_string,
            model=model,
            domain=domain,
            component=component,
            action=action,
            verbosity=v,
            summary_template=summary_template,
        )
    )


def register_event(
    event_class: type[SootheEvent],
    verbosity: VerbosityTier | None = None,
    summary_template: str = "",
) -> None:
    """Register an event class with the global event registry.

    This is the public API for registering events from modules and plugins.
    It auto-extracts the type string from the event class's Pydantic model
    and sets appropriate defaults based on the event's domain.

    **Usage**:

    ```python
    from soothe.core.event_catalog import register_event
    from soothe.foundation.base_events import SootheEvent


    class MyCustomEvent(SootheEvent):
        type: str = "soothe.plugin.custom.event"
        data: str


    # Register the event
    register_event(
        MyCustomEvent,
        verbosity="tool_activity",
        summary_template="Custom event: {data}",
    )
    ```

    Args:
        event_class: Event class to register (must have 'type' field with default value).
        verbosity: Optional verbosity category. If not provided, inferred from domain.
        summary_template: Optional template for event summaries (supports field interpolation).

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
    _reg(type_string, event_class, verbosity=verbosity, summary_template=summary_template)


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
    "soothe.cognition.agent_loop.started",
    AgenticLoopStartedEvent,
    verbosity=VerbosityTier.NORMAL,
    summary_template="{goal}",
)
_reg(
    "soothe.cognition.agent_loop.completed",
    AgenticLoopCompletedEvent,
    verbosity=VerbosityTier.QUIET,
    summary_template="Done: {completion_summary}",
)
_reg(
    "soothe.agentic.step.started",
    AgenticStepStartedEvent,
    verbosity=VerbosityTier.NORMAL,  # RFC-0020: Step descriptions visible at normal verbosity
    summary_template="{description}",
)
_reg(
    "soothe.agentic.step.completed",
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
_reg(PLAN_BATCH_STARTED, PlanBatchStartedEvent, summary_template="Batch: {parallel_count} steps in parallel")
_reg(PLAN_REFLECTED, PlanReflectedEvent, summary_template="Reflected: {assessment}")
_reg(PLAN_DAG_SNAPSHOT, PlanDagSnapshotEvent, verbosity=VerbosityTier.DEBUG)

# -- Protocol: policy --------------------------------------------------------
_reg(POLICY_CHECKED, PolicyCheckedEvent, summary_template="Policy: {verdict}")
_reg(POLICY_DENIED, PolicyDeniedEvent, summary_template="Denied: {reason}")

# -- Protocol: goal ----------------------------------------------------------
_reg(GOAL_CREATED, GoalCreatedEvent, summary_template="Goal: {description} (priority={priority})")
_reg(GOAL_COMPLETED, GoalCompletedEvent, summary_template="Goal {goal_id} completed")
_reg(GOAL_FAILED, GoalFailedEvent, summary_template="Goal {goal_id} failed (retry {retry_count})")
_reg(GOAL_BATCH_STARTED, GoalBatchStartedEvent, summary_template="Goals: {parallel_count} running in parallel")
_reg(GOAL_REPORT, GoalReportEvent, summary_template="[goal] {goal_id}: {completed}/{step_count} steps")
_reg(
    GOAL_DIRECTIVES_APPLIED,
    GoalDirectivesAppliedEvent,
    summary_template="Directives applied: {directives_count} changes",
)
_reg(GOAL_DEFERRED, GoalDeferredEvent, summary_template="Goal {goal_id} deferred: {reason}")

# -- Output ------------------------------------------------------------------
_reg(CHITCHAT_STARTED, ChitchatStartedEvent, verbosity=VerbosityTier.INTERNAL)
_reg(CHITCHAT_RESPONSE, ChitchatResponseEvent, verbosity=VerbosityTier.QUIET)
_reg(FINAL_REPORT, FinalReportEvent, verbosity=VerbosityTier.QUIET)

# -- Autopilot (RFC-204) -------------------------------------------------
AUTOPILLOT_STATUS_CHANGED = "soothe.autopilot.status_changed"
AUTOPILLOT_GOAL_CREATED = "soothe.autopilot.goal_created"
AUTOPILLOT_GOAL_PROGRESS = "soothe.autopilot.goal_progress"
AUTOPILLOT_GOAL_COMPLETED = "soothe.autopilot.goal_completed"
AUTOPILLOT_DREAMING_ENTERED = "soothe.autopilot.dreaming_entered"
AUTOPILLOT_DREAMING_EXITED = "soothe.autopilot.dreaming_exited"
AUTOPILLOT_GOAL_VALIDATED = "soothe.autopilot.goal_validated"
AUTOPILLOT_GOAL_SUSPENDED = "soothe.autopilot.goal_suspended"
AUTOPILLOT_SEND_BACK = "soothe.autopilot.send_back"
AUTOPILLOT_RELATIONSHIP_DETECTED = "soothe.autopilot.relationship_detected"
AUTOPILLOT_CHECKPOINT_SAVED = "soothe.autopilot.checkpoint.saved"
AUTOPILLOT_GOAL_BLOCKED = "soothe.autopilot.goal_blocked"


class _AutopilotStatusChanged(SootheEvent):
    type: str = "soothe.autopilot.status_changed"
    state: str


class _AutopilotGoalCreated(SootheEvent):
    type: str = "soothe.autopilot.goal_created"
    goal_id: str
    description: str = ""


class _AutopilotGoalProgress(SootheEvent):
    type: str = "soothe.autopilot.goal_progress"
    goal_id: str
    status: str = ""


class _AutopilotGoalCompleted(SootheEvent):
    type: str = "soothe.autopilot.goal_completed"
    goal_id: str


class _AutopilotDreamingEntered(SootheEvent):
    type: str = "soothe.autopilot.dreaming_entered"
    timestamp: str = ""


class _AutopilotDreamingExited(SootheEvent):
    type: str = "soothe.autopilot.dreaming_exited"
    timestamp: str = ""
    trigger: str = ""


class _AutopilotGoalValidated(SootheEvent):
    type: str = "soothe.autopilot.goal_validated"
    goal_id: str
    confidence: float = 1.0


class _AutopilotGoalSuspended(SootheEvent):
    type: str = "soothe.autopilot.goal_suspended"
    goal_id: str
    reason: str = ""


class _AutopilotSendBack(SootheEvent):
    type: str = "soothe.autopilot.send_back"
    goal_id: str
    remaining_budget: int = 0
    feedback: str = ""


class _AutopilotRelationshipDetected(SootheEvent):
    type: str = "soothe.autopilot.relationship_detected"
    from_goal: str
    to_goal: str
    relationship_type: str
    confidence: float = 0.0


class _AutopilotCheckpointSaved(SootheEvent):
    type: str = "soothe.autopilot.checkpoint.saved"
    thread_id: str
    trigger: str = ""


class _AutopilotGoalBlocked(SootheEvent):
    type: str = "soothe.autopilot.goal_blocked"
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
_reg(AUTOPILLOT_RELATIONSHIP_DETECTED, _AutopilotRelationshipDetected, verbosity=VerbosityTier.DETAILED)
_reg(AUTOPILLOT_CHECKPOINT_SAVED, _AutopilotCheckpointSaved, verbosity=VerbosityTier.DETAILED)
_reg(AUTOPILLOT_GOAL_BLOCKED, _AutopilotGoalBlocked, verbosity=VerbosityTier.NORMAL)


# ---------------------------------------------------------------------------
# Import event modules to trigger self-registration
# These modules call register_event() at import time
# Must be at the end after all core events are registered
# ---------------------------------------------------------------------------
