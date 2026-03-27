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
from typing import TYPE_CHECKING, Any, Literal

from soothe.core.base_events import (
    ErrorEvent,
    LifecycleEvent,
    OutputEvent,
    ProtocolEvent,
    SootheEvent,
    ToolEvent,
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

# -- Protocol events ---------------------------------------------------------
CONTEXT_PROJECTED = "soothe.protocol.context.projected"
CONTEXT_INGESTED = "soothe.protocol.context.ingested"
MEMORY_RECALLED = "soothe.protocol.memory.recalled"
MEMORY_STORED = "soothe.protocol.memory.stored"
PLAN_CREATED = "soothe.cognition.plan.created"
PLAN_STEP_STARTED = "soothe.cognition.plan.step_started"
PLAN_STEP_COMPLETED = "soothe.cognition.plan.step_completed"
PLAN_STEP_FAILED = "soothe.cognition.plan.step_failed"
PLAN_BATCH_STARTED = "soothe.cognition.plan.batch_started"
PLAN_REFLECTED = "soothe.cognition.plan.reflected"
PLAN_DAG_SNAPSHOT = "soothe.cognition.plan.dag_snapshot"
PLAN_ONLY = "soothe.cognition.plan.plan_only"
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
PLUGIN_HEALTH_CHECKED = "soothe.plugin.health_checked"


# ---------------------------------------------------------------------------
# Core event class definitions
# ---------------------------------------------------------------------------

if TYPE_CHECKING:
    from soothe.ux.core.progress_verbosity import ProgressCategory

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


# ---------------------------------------------------------------------------
# Agentic loop events (RFC-0008)
# ---------------------------------------------------------------------------


class AgenticLoopStartedEvent(LifecycleEvent):
    type: Literal["soothe.agentic.loop.started"] = "soothe.agentic.loop.started"
    thread_id: str
    query: str
    max_iterations: int
    observation_strategy: str
    verification_strictness: str


class AgenticLoopCompletedEvent(LifecycleEvent):
    type: Literal["soothe.agentic.loop.completed"] = "soothe.agentic.loop.completed"
    thread_id: str
    total_iterations: int
    outcome: str  # "completed" | "failed" | "escalated"


class AgenticIterationStartedEvent(LifecycleEvent):
    type: Literal["soothe.agentic.iteration.started"] = "soothe.agentic.iteration.started"
    iteration: int
    planning_strategy: str


class AgenticIterationCompletedEvent(LifecycleEvent):
    type: Literal["soothe.agentic.iteration.completed"] = "soothe.agentic.iteration.completed"
    iteration: int
    planning_strategy: str
    outcome: str
    duration_ms: int


class AgenticObservationStartedEvent(ProtocolEvent):
    type: Literal["soothe.agentic.observation.started"] = "soothe.agentic.observation.started"
    iteration: int
    strategy: str


class AgenticObservationCompletedEvent(ProtocolEvent):
    type: Literal["soothe.agentic.observation.completed"] = "soothe.agentic.observation.completed"
    iteration: int
    context_entries: int
    memories_recalled: int
    planning_strategy: str


class AgenticVerificationStartedEvent(ProtocolEvent):
    type: Literal["soothe.agentic.verification.started"] = "soothe.agentic.verification.started"
    iteration: int
    strictness: str


class AgenticVerificationCompletedEvent(ProtocolEvent):
    type: Literal["soothe.agentic.verification.completed"] = "soothe.agentic.verification.completed"
    iteration: int
    should_continue: bool
    assessment: str


class AgenticPlanningStrategyDeterminedEvent(ProtocolEvent):
    type: Literal["soothe.agentic.planning.strategy_determined"] = "soothe.agentic.planning.strategy_determined"
    iteration: int
    complexity: str
    strategy: str
    reason: str


# ---------------------------------------------------------------------------
# Protocol events
# ---------------------------------------------------------------------------


class ContextProjectedEvent(ProtocolEvent):
    type: Literal["soothe.protocol.context.projected"] = "soothe.protocol.context.projected"
    entries: int = 0
    tokens: int = 0


class ContextIngestedEvent(ProtocolEvent):
    type: Literal["soothe.protocol.context.ingested"] = "soothe.protocol.context.ingested"
    source: str = ""
    content_preview: str = ""


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
    goal: str = ""
    steps: list[dict[str, Any]] = []  # noqa: RUF012


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


class PlanOnlyEvent(ProtocolEvent):
    type: Literal["soothe.cognition.plan.plan_only"] = "soothe.cognition.plan.plan_only"
    thread_id: str = ""
    goal: str = ""
    step_count: int = 0


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
# Tool events
# ---------------------------------------------------------------------------


class ToolStartedEvent(ToolEvent):
    tool: str
    args: str = ""
    kwargs: str = ""


class ToolCompletedEvent(ToolEvent):
    tool: str
    result_preview: str = ""


class ToolFailedEvent(ToolEvent):
    tool: str
    error: str = ""


def make_tool_started(tool_name: str, *, tool_group: str | None = None, **extra: Any) -> dict[str, Any]:
    """Build a main-agent tool-started event dict.

    Args:
        tool_name: Internal tool name (e.g. ``search_web``).
        tool_group: User-facing tool group (e.g. ``websearch``).
            When provided the type uses ``soothe.tool.<group>.<tool>_started``;
            otherwise falls back to ``soothe.tool.<tool>.started``.
        **extra: Additional event payload fields.
    """
    grp = tool_group or tool_name
    etype = f"soothe.tool.{tool_group}.{tool_name}_started" if tool_group else f"soothe.tool.{tool_name}.started"
    return {"type": etype, "tool": tool_name, "tool_group": grp, **extra}


def make_tool_completed(tool_name: str, *, tool_group: str | None = None, **extra: Any) -> dict[str, Any]:
    """Build a main-agent tool-completed event dict.

    Args:
        tool_name: Internal tool name.
        tool_group: User-facing tool group.
        **extra: Additional event payload fields.
    """
    grp = tool_group or tool_name
    etype = f"soothe.tool.{tool_group}.{tool_name}_completed" if tool_group else f"soothe.tool.{tool_name}.completed"
    return {"type": etype, "tool": tool_name, "tool_group": grp, **extra}


def make_tool_failed(tool_name: str, *, tool_group: str | None = None, **extra: Any) -> dict[str, Any]:
    """Build a main-agent tool-failed event dict.

    Args:
        tool_name: Internal tool name.
        tool_group: User-facing tool group.
        **extra: Additional event payload fields.
    """
    grp = tool_group or tool_name
    etype = f"soothe.tool.{tool_group}.{tool_name}_failed" if tool_group else f"soothe.tool.{tool_name}.failed"
    return {"type": etype, "tool": tool_name, "tool_group": grp, **extra}


# ---------------------------------------------------------------------------
# Tool and subagent event helpers
# ---------------------------------------------------------------------------

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
# Error events
# ---------------------------------------------------------------------------


class GeneralErrorEvent(ErrorEvent):
    type: Literal["soothe.error.general"] = "soothe.error.general"
    error: str


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
    verbosity: ProgressCategory
    summary_template: str = ""


_DOMAIN_DEFAULT_VERBOSITY: dict[str, ProgressCategory] = {
    "lifecycle": "protocol",
    "protocol": "protocol",
    "tool": "tool_activity",
    "subagent": "subagent_custom",
    "output": "assistant_text",
    "error": "error",
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

    def get_verbosity(self, event_type: str) -> str:
        """Return the verbosity category for an event type."""
        meta = self._by_type.get(event_type)
        if meta:
            return meta.verbosity
        domain = self.classify(event_type)
        return _DOMAIN_DEFAULT_VERBOSITY.get(domain, "debug")

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
    verbosity: ProgressCategory | None = None,
    summary_template: str = "",
) -> None:
    """Internal helper for registering core events.

    Args:
        type_string: Event type string (e.g., "soothe.lifecycle.thread.created").
        model: Event model class.
        verbosity: Optional verbosity category override.
        summary_template: Optional template for event summaries.
    """
    parts = type_string.split(".")
    domain = parts[1] if len(parts) >= 2 else "unknown"
    component = parts[2] if len(parts) >= 3 else ""
    action = parts[3] if len(parts) >= 4 else ""
    v = verbosity or _DOMAIN_DEFAULT_VERBOSITY.get(domain, "debug")
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
    verbosity: ProgressCategory | None = None,
    summary_template: str = "",
) -> None:
    """Register an event class with the global event registry.

    This is the public API for registering events from modules and plugins.
    It auto-extracts the type string from the event class's Pydantic model
    and sets appropriate defaults based on the event's domain.

    **Usage**:

    ```python
    from soothe.core.event_catalog import register_event
    from soothe.core.base_events import SootheEvent


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

# -- Agentic Loop (RFC-0008) -------------------------------------------------
_reg(
    "soothe.agentic.loop.started",
    AgenticLoopStartedEvent,
    summary_template="Agentic loop started (max {max_iterations} iterations)",
)
_reg(
    "soothe.agentic.loop.completed",
    AgenticLoopCompletedEvent,
    summary_template="Agentic loop completed: {total_iterations} iterations, {outcome}",
)
_reg(
    "soothe.agentic.iteration.started",
    AgenticIterationStartedEvent,
    summary_template="Iteration {iteration} ({planning_strategy} planning)",
)
_reg(
    "soothe.agentic.iteration.completed",
    AgenticIterationCompletedEvent,
    summary_template="Iteration {iteration}: {outcome} ({duration_ms}ms)",
)
_reg(
    "soothe.agentic.observation.started",
    AgenticObservationStartedEvent,
    verbosity="debug",
    summary_template="Observation started (strategy={strategy})",
)
_reg(
    "soothe.agentic.observation.completed",
    AgenticObservationCompletedEvent,
    verbosity="debug",
    summary_template="Observed: {context_entries} context, {memories_recalled} memories → {planning_strategy}",
)
_reg(
    "soothe.agentic.verification.started",
    AgenticVerificationStartedEvent,
    verbosity="debug",
    summary_template="Verification started (strictness={strictness})",
)
_reg(
    "soothe.agentic.verification.completed",
    AgenticVerificationCompletedEvent,
    verbosity="debug",
    summary_template="Verified: {'continue' if should_continue else 'stop'}",
)
_reg(
    "soothe.agentic.planning.strategy_determined",
    AgenticPlanningStrategyDeterminedEvent,
    summary_template="Planning strategy: {strategy} (complexity={complexity}, reason={reason})",
)

# -- Protocol: context -------------------------------------------------------
_reg(CONTEXT_PROJECTED, ContextProjectedEvent, summary_template="{entries} entries, {tokens} tokens")
_reg(CONTEXT_INGESTED, ContextIngestedEvent, summary_template="Ingested from {source}")

# -- Protocol: memory --------------------------------------------------------
_reg(MEMORY_RECALLED, MemoryRecalledEvent, summary_template="{count} items recalled")
_reg(MEMORY_STORED, MemoryStoredEvent, summary_template="Stored memory: {id}")

# -- Protocol: plan ----------------------------------------------------------
_reg(PLAN_CREATED, PlanCreatedEvent, summary_template="Plan: {goal}")
_reg(PLAN_STEP_STARTED, PlanStepStartedEvent, summary_template="Step {step_id}: {description}")
_reg(PLAN_STEP_COMPLETED, PlanStepCompletedEvent, summary_template="Step {step_id}: done")
_reg(PLAN_STEP_FAILED, PlanStepFailedEvent, summary_template="Step {step_id}: FAILED - {error}")
_reg(PLAN_BATCH_STARTED, PlanBatchStartedEvent, summary_template="Batch: {parallel_count} steps in parallel")
_reg(PLAN_REFLECTED, PlanReflectedEvent, summary_template="Reflected: {assessment}")
_reg(PLAN_DAG_SNAPSHOT, PlanDagSnapshotEvent, verbosity="debug")
_reg(PLAN_ONLY, PlanOnlyEvent, summary_template="Plan only: {step_count} steps")

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
_reg(CHITCHAT_STARTED, ChitchatStartedEvent, summary_template="Chitchat: {query}")
_reg(CHITCHAT_RESPONSE, ChitchatResponseEvent, verbosity="assistant_text")
_reg(FINAL_REPORT, FinalReportEvent, verbosity="assistant_text")

# -- Error -------------------------------------------------------------------
_reg(ERROR, GeneralErrorEvent, verbosity="error", summary_template="{error}")


# ---------------------------------------------------------------------------
# Import event modules to trigger self-registration
# These modules call register_event() at import time
# Must be at the end after all core events are registered
# ---------------------------------------------------------------------------
import soothe.plugin.events  # noqa: E402
import soothe.subagents.browser.events  # noqa: E402
import soothe.subagents.claude.events  # noqa: E402
import soothe.subagents.research.events  # noqa: E402
import soothe.subagents.skillify.events  # noqa: E402
import soothe.subagents.weaver.events  # noqa: E402
import soothe.tools.audio.events  # noqa: E402
import soothe.tools.code_edit.events  # noqa: E402
import soothe.tools.data.events  # noqa: E402
import soothe.tools.execution.events  # noqa: E402
import soothe.tools.file_ops.events  # noqa: E402
import soothe.tools.goals.events  # noqa: E402
import soothe.tools.image.events  # noqa: E402
import soothe.tools.video.events  # noqa: E402
import soothe.tools.web_search.events  # noqa: F401, E402
