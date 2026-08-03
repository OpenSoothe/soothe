"""Event type constants, models, and registry for soothe.* events.

This module is the single source of truth for host event type strings and
Pydantic event models, plus registry registration and emission helpers.

Client-facing: ``soothe.<domain>.<component>.<action>`` (RFC-0015).
Internal (daemon/worker only, never WebSocket broadcast):
``soothe.internal.<component>.<action>``.

Base event classes are defined in soothe_sdk.core.events.
Module-specific events (subagents, tools) are defined in their respective
modules and imported here for registry.

**Usage:**

For type-safe event emission (recommended):
    from soothe.events import GoalCreatedEvent
    yield custom_event(GoalCreatedEvent(goal_id=gid).to_dict())

For event type string constants:
    from soothe.events import GOAL_CREATED, PLAN_CREATED
    if event_type == GOAL_CREATED:
        ...
"""

from __future__ import annotations

from typing import Any, Literal

# Protocol-primitive event models (stream-end, memory, policy) are owned by
# nano. Re-exported here for ``soothe.events`` consumers. Nano registers them;
# host must not re-_reg them.
from soothe_nano.events.catalog import (  # noqa: F401
    MemoryRecalledEvent,
    MemoryStoredEvent,
    PolicyCheckedEvent,
    PolicyDeniedEvent,
    StreamEndEvent,
)
from soothe_sdk.core.events import (
    LifecycleEvent,
    ProtocolEvent,
    SootheEvent,
)
from soothe_sdk.core.verbosity import VerbosityTier

# ============================================================================
# INTERNAL NAMESPACE (soothe.internal.*) — never broadcast to clients
# ============================================================================

# Iteration
ITERATION_STARTED = "soothe.internal.iteration.started"
ITERATION_COMPLETED = "soothe.internal.iteration.completed"

# Checkpoint
CHECKPOINT_SAVED = "soothe.internal.checkpoint.saved"

# Recovery
RECOVERY_RESUMED = "soothe.internal.recovery.resumed"

# Loop lifecycle
LOOP_CREATED = "soothe.internal.loop.created"
LOOP_STARTED = "soothe.internal.loop.started"
LOOP_COMPLETED = "soothe.internal.loop.completed"

# Control-plane replay marker (prefer wire ``replay_complete`` envelope to clients)
REPLAY_COMPLETE = "replay_complete"

# Daemon
DAEMON_HEARTBEAT = "soothe.internal.daemon.heartbeat"

# Config hot-reload
CONFIG_RELOADED = "soothe.system.config.reloaded"

# Plugin lifecycle
PLUGIN_LOADED = "soothe.internal.plugin.loaded"
PLUGIN_FAILED = "soothe.internal.plugin.failed"
PLUGIN_UNLOADED = "soothe.internal.plugin.unloaded"

# Plan internals
PLAN_DAG_SNAPSHOT = "soothe.internal.plan.dag_snapshot"
PLAN_BATCH_STARTED = "soothe.internal.plan.batch.started"

# Skill internals
SKILL_BODY_LOADED = "soothe.internal.skill.body.loaded"

# MCP internals
MCP_LIST_CHANGED = "soothe.internal.mcp.list_changed"
MCP_TOOL_TIMEOUT = "soothe.internal.mcp.tool.timeout"

# Branch internals
BRANCH_ANALYZED = "soothe.internal.branch.analyzed"
BRANCH_PRUNED = "soothe.internal.branch.pruned"

# Autopilot internals (DETAILED)
AUTOPILOT_GOAL_VALIDATED = "soothe.internal.autopilot.goal.validated"
AUTOPILOT_FEEDBACK_SENT = "soothe.internal.autopilot.feedback.sent"
AUTOPILOT_RELATIONSHIP_DETECTED = "soothe.internal.autopilot.relationship.detected"
AUTOPILOT_CHECKPOINT_SAVED = "soothe.internal.autopilot.checkpoint.saved"

# ============================================================================
# CLIENT-FACING (soothe.<domain>.*)
# ============================================================================

# Goal cognition
GOAL_CREATED = "soothe.cognition.goal.created"
GOAL_COMPLETED = "soothe.cognition.goal.completed"
GOAL_FAILED = "soothe.cognition.goal.failed"
GOAL_REMOVED = "soothe.cognition.goal.removed"
GOAL_DECOMPOSED = "soothe.cognition.goal.decomposed"
GOAL_BATCH_STARTED = "soothe.cognition.goal.batch.started"
GOAL_REPORT = "soothe.cognition.goal.reported"
GOAL_DIRECTIVES_APPLIED = "soothe.cognition.goal.directives.applied"
GOAL_DEFERRED = "soothe.cognition.goal.deferred"

# Autopilot mode switching
AUTOPILOT_MODE_SWITCHED = "soothe.cognition.autopilot.mode_switched"

# Intent classification (IG-518)
INTENT_CLASSIFIED = "soothe.cognition.intent.classified"

# Plan cognition (client UX)
PLAN_CREATED = "soothe.cognition.plan.created"
PLAN_REFLECTED = "soothe.cognition.plan.reflected"

# StrangeLoop cognition
STRANGE_LOOP_STARTED = "soothe.cognition.strange_loop.started"
STRANGE_LOOP_COMPLETED = "soothe.cognition.strange_loop.completed"
STRANGE_LOOP_STEP_STARTED = "soothe.cognition.strange_loop.step.started"
STRANGE_LOOP_STEP_QUEUED = "soothe.cognition.strange_loop.step.queued"
STRANGE_LOOP_STEP_COMPLETED = "soothe.cognition.strange_loop.step.completed"
STRANGE_LOOP_PLAN_DECISION = "soothe.cognition.strange_loop.plan.decision"
STRANGE_LOOP_PLAN_PHASE = "soothe.cognition.strange_loop.plan.phase"
STRANGE_LOOP_REASONED = "soothe.cognition.strange_loop.reasoned"
STRANGE_LOOP_CONTEXT_COMPACTED = "soothe.cognition.strange_loop.context.compacted"  # RFC-224

# Intake-only wired specialist lifecycle (IG-602 / RFC-630 §6.3.3)
WIRED_SUBAGENT_STARTED = "soothe.cognition.wired_subagent.started"
WIRED_SUBAGENT_COMPLETED = "soothe.cognition.wired_subagent.completed"
WIRED_SUBAGENT_FAILED = "soothe.cognition.wired_subagent.failed"
WIRED_SUBAGENT_CANCELLED = "soothe.cognition.wired_subagent.cancelled"

# Branch cognition (client UX)
BRANCH_CREATED = "soothe.cognition.branch.created"
BRANCH_RETRY_STARTED = "soothe.cognition.branch.retry.started"

# Autopilot system (client UX)
AUTOPILOT_STATUS_CHANGED = "soothe.system.autopilot.status.changed"
AUTOPILOT_GOAL_CREATED = "soothe.system.autopilot.goal.created"
AUTOPILOT_GOAL_REPORTED = "soothe.system.autopilot.goal.reported"
AUTOPILOT_GOAL_COMPLETED = "soothe.system.autopilot.goal.completed"
AUTOPILOT_DREAMING_STARTED = "soothe.system.autopilot.dreaming.started"
AUTOPILOT_DREAMING_COMPLETED = "soothe.system.autopilot.dreaming.completed"
AUTOPILOT_GOAL_SUSPENDED = "soothe.system.autopilot.goal.suspended"
AUTOPILOT_GOAL_BLOCKED = "soothe.system.autopilot.goal.blocked"

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
        Stream chunk in canonical (namespace, mode, data) format.
    """
    return ((), "custom", data)


# ---------------------------------------------------------------------------
# Event models
# All event types follow RFC-0015's 4-segment naming convention:
# ``soothe.<domain>.<component>.<action>``
# ---------------------------------------------------------------------------


class IterationStartedEvent(LifecycleEvent):
    type: Literal["soothe.internal.iteration.started"] = "soothe.internal.iteration.started"
    iteration: int | str
    goal_id: str = ""
    goal_description: str = ""
    parallel_goals: int = 1


class IterationCompletedEvent(LifecycleEvent):
    type: Literal["soothe.internal.iteration.completed"] = "soothe.internal.iteration.completed"
    iteration: int | str
    goal_id: str = ""
    outcome: str = ""
    duration_ms: int = 0


class CheckpointSavedEvent(LifecycleEvent):
    type: Literal["soothe.internal.checkpoint.saved"] = "soothe.internal.checkpoint.saved"
    thread_id: str
    completed_steps: int = 0
    completed_goals: int = 0


class RecoveryResumedEvent(LifecycleEvent):
    type: Literal["soothe.internal.recovery.resumed"] = "soothe.internal.recovery.resumed"
    thread_id: str
    completed_steps: list[str] = []  # noqa: RUF012
    completed_goals: list[str] = []  # noqa: RUF012
    mode: str = ""


class LoopCreatedEvent(LifecycleEvent):
    type: Literal["soothe.internal.loop.created"] = "soothe.internal.loop.created"
    loop_id: str
    thread_id: str = ""


class LoopStartedEvent(LifecycleEvent):
    type: Literal["soothe.internal.loop.started"] = "soothe.internal.loop.started"
    loop_id: str
    thread_id: str = ""
    protocols: list[str] = []  # noqa: RUF012


class LoopCompletedEvent(LifecycleEvent):
    type: Literal["soothe.internal.loop.completed"] = "soothe.internal.loop.completed"
    loop_id: str
    thread_id: str = ""


class DaemonHeartbeatEvent(LifecycleEvent):
    """Heartbeat event broadcast by daemon to keep clients alive during long operations.

    RFC-0013: Daemon broadcasts heartbeat every 5 seconds to subscribed clients.
    This prevents client timeout when LLM operations take longer than the client's
    query start timeout (default 20 seconds).
    """

    type: Literal["soothe.internal.daemon.heartbeat"] = "soothe.internal.daemon.heartbeat"
    thread_id: str = ""
    timestamp: str = ""  # ISO format timestamp
    state: str = "running"  # "running" | "idle"


class ConfigReloadedEvent(SootheEvent):
    """Event emitted when a configuration file is hot-reloaded.

    Emitted by the daemon when config files are modified or when a SIGHUP signal
    triggers a reload. Downstream subscribers can use this to react to config changes
    without restarting the daemon.

    Attributes:
        config_type: Type of config that was reloaded ('agent' or 'daemon').
        config_path: Path to the config file that was reloaded.
        old_config: Previous config state (serialized to dict for wire safety).
        new_config: New config state (serialized to dict for wire safety).
        old_config_hash: SHA256 hash (truncated) of old config for comparison.
        new_config_hash: SHA256 hash (truncated) of new config for comparison.
        timestamp: ISO format timestamp when the reload occurred.
        success: Whether the reload succeeded.
        error: Error message if reload failed, None on success.
    """

    type: Literal["soothe.system.config.reloaded"] = "soothe.system.config.reloaded"
    config_type: str  # 'agent' or 'daemon'
    config_path: str = ""
    old_config: dict[str, Any] = {}  # noqa: RUF012
    new_config: dict[str, Any] = {}  # noqa: RUF012
    old_config_hash: str = ""
    new_config_hash: str = ""
    timestamp: str = ""  # ISO format
    success: bool = True
    error: str | None = None


# ---------------------------------------------------------------------------
# StrangeLoop events (RFC-0008) - formerly Agentic loop events
# ---------------------------------------------------------------------------


class StrangeLoopStartedEvent(LifecycleEvent):
    type: Literal["soothe.cognition.strange_loop.started"] = "soothe.cognition.strange_loop.started"
    thread_id: str
    goal: str
    max_iterations: int


class StrangeLoopCompletedEvent(LifecycleEvent):
    type: Literal["soothe.cognition.strange_loop.completed"] = (
        "soothe.cognition.strange_loop.completed"
    )
    thread_id: str
    status: str
    goal_progress: Literal[
        "none", "low", "medium", "high", "complete"
    ]  # IG-399: descriptive levels
    evidence_summary: str
    # IG-267: Include goal for CLI display trophy message
    goal: str = ""
    # One-line UI summary for TUI/registry (avoid duplicating streamed full_output).
    completion_summary: str = ""
    # Layer-2 act steps completed in this thread (for goal-done line when pipeline has 0).
    total_steps: int = 0


class StrangeLoopPlanDecisionEvent(LifecycleEvent):
    """Planned act steps for this iteration (includes not-yet-ready steps).

    Includes cumulative step counts across all iterations for TUI display.
    """

    type: Literal["soothe.cognition.strange_loop.plan.decision"] = (
        "soothe.cognition.strange_loop.plan.decision"
    )
    iteration: int = 0
    steps: list[dict[str, Any]] = []  # noqa: RUF012
    execution_mode: str = ""
    intake_label: str = ""
    total_steps: int = 0  # Cumulative total steps across all iterations
    done_steps: int = 0  # Cumulative completed steps across all iterations


class StrangeLoopPlanPhaseStatusEvent(LifecycleEvent):
    """In-flight plan assess/generate label for TUI spinner (not a chat card)."""

    type: Literal["soothe.cognition.strange_loop.plan.phase"] = (
        "soothe.cognition.strange_loop.plan.phase"
    )
    label: str
    total_tokens_used: int = 0


class WiredSubagentStartedEvent(LifecycleEvent):
    """Intake-only wired specialist began (orphan SubAgent card mount)."""

    type: Literal["soothe.cognition.wired_subagent.started"] = (
        "soothe.cognition.wired_subagent.started"
    )
    subagent: str
    invocation_id: str
    step_id: str
    description: str = ""


class WiredSubagentCompletedEvent(LifecycleEvent):
    """Intake-only wired specialist finished successfully."""

    type: Literal["soothe.cognition.wired_subagent.completed"] = (
        "soothe.cognition.wired_subagent.completed"
    )
    subagent: str
    invocation_id: str
    step_id: str = ""
    duration_ms: int = 0
    summary: str = ""


class WiredSubagentFailedEvent(LifecycleEvent):
    """Intake-only wired specialist failed."""

    type: Literal["soothe.cognition.wired_subagent.failed"] = (
        "soothe.cognition.wired_subagent.failed"
    )
    subagent: str
    invocation_id: str
    step_id: str = ""
    duration_ms: int = 0
    summary: str = ""
    error: str = ""


class WiredSubagentCancelledEvent(LifecycleEvent):
    """Intake-only wired specialist cancelled (disconnect / interrupt)."""

    type: Literal["soothe.cognition.wired_subagent.cancelled"] = (
        "soothe.cognition.wired_subagent.cancelled"
    )
    subagent: str
    invocation_id: str
    step_id: str = ""
    duration_ms: int = 0
    summary: str = ""


class StrangeLoopStepStartedEvent(LifecycleEvent):
    """Level 2: Step description in three-level tree (RFC-0020)."""

    type: Literal["soothe.cognition.strange_loop.step.started"] = (
        "soothe.cognition.strange_loop.step.started"
    )
    step_id: str
    description: str


class StrangeLoopStepQueuedEvent(LifecycleEvent):
    """Ready step waiting for a later execute batch (concurrency cap)."""

    type: Literal["soothe.cognition.strange_loop.step.queued"] = (
        "soothe.cognition.strange_loop.step.queued"
    )
    step_id: str
    description: str


class StrangeLoopStepCompletedEvent(LifecycleEvent):
    """Level 3: Step result in three-level tree (RFC-0020).

    For ``ask_user`` steps resolved by veritas / interactive relay, the optional
    ``clarification`` field carries the questions, the answers, the answer
    source (``veritas`` / ``human`` / ``fallback``) and (when known) the
    veritas confidence so live UIs can render the Q&A on the step card.
    """

    type: Literal["soothe.cognition.strange_loop.step.completed"] = (
        "soothe.cognition.strange_loop.step.completed"
    )
    step_id: str
    success: bool
    summary: str
    duration_ms: int
    tool_call_count: int = 0
    clarification: dict[str, Any] | None = None
    total_tokens_used: int = 0


class StrangeLoopContextCompactionEvent(LifecycleEvent):
    """Context window compaction event (RFC-224).

    Emitted when automatic context compaction occurs to stay within
    configured threshold. Provides visibility into context management
    for observability.
    """

    type: Literal["soothe.cognition.strange_loop.context.compacted"] = (
        "soothe.cognition.strange_loop.context.compacted"
    )
    thread_id: str
    tokens_before: int
    tokens_after: int
    messages_removed: int
    summary_preview: str | None = None


# ---------------------------------------------------------------------------
# Protocol events
# ---------------------------------------------------------------------------


class PlanCreatedEvent(ProtocolEvent):
    type: Literal["soothe.cognition.plan.created"] = "soothe.cognition.plan.created"
    plan_id: str = ""
    goal: str = ""
    steps: list[dict[str, Any]] = []  # noqa: RUF012
    reasoning: str | None = None
    is_plan_only: bool = False


class PlanBatchStartedEvent(ProtocolEvent):
    type: Literal["soothe.internal.plan.batch.started"] = "soothe.internal.plan.batch.started"
    batch_index: int = 0
    step_ids: list[str] = []  # noqa: RUF012
    parallel_count: int = 1


class PlanReflectedEvent(ProtocolEvent):
    type: Literal["soothe.cognition.plan.reflected"] = "soothe.cognition.plan.reflected"
    should_revise: bool = False
    assessment: str = ""


class PlanDagSnapshotEvent(ProtocolEvent):
    type: Literal["soothe.internal.plan.dag_snapshot"] = "soothe.internal.plan.dag_snapshot"
    steps: list[dict[str, Any]] = []  # noqa: RUF012


class IntentClassifiedEvent(ProtocolEvent):
    """Intent classification result for client visibility (IG-518).

    Emitted after intent-classify determines an agentic intent,
    providing reasoning for why the query requires tool execution
    rather than a direct chitchat-style response.
    """

    type: Literal["soothe.cognition.intent.classified"] = "soothe.cognition.intent.classified"
    intent_type: str = "agentic"
    reasoning: str | None = None
    intake_label: str = ""


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


class GoalRemovedEvent(ProtocolEvent):
    """Goal removed from DAG (RFC-625).

    Emitted when a goal is removed from the ContextEngine DAG,
    typically during cleanup or restructuring operations.
    """

    type: Literal["soothe.cognition.goal.removed"] = "soothe.cognition.goal.removed"
    goal_id: str = ""
    reason: str = ""


class GoalDecomposedEvent(ProtocolEvent):
    """Goal decomposed into sub-goals (RFC-625).

    Emitted when a complex goal is decomposed into multiple sub-goals
    by the AutopilotMonitor or DAG verification process.
    """

    type: Literal["soothe.cognition.goal.decomposed"] = "soothe.cognition.goal.decomposed"
    parent_goal_id: str = ""
    child_goal_ids: list[str] = []  # noqa: RUF012


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


class AutopilotModeSwitchedEvent(ProtocolEvent):
    """Autopilot mode switched (RFC-625).

    Emitted when autopilot mode is toggled on/off for a loop.
    Used by TUI and other subscribers to update their state.
    """

    type: Literal["soothe.cognition.autopilot.mode_switched"] = (
        "soothe.cognition.autopilot.mode_switched"
    )
    loop_id: str = ""
    enabled: bool = False


# ---------------------------------------------------------------------------
# Registry — re-exported from soothe_sdk.core.registry (canonical owner)
# ---------------------------------------------------------------------------
# The EventPriority / EventMeta / EventRegistry trio, the REGISTRY singleton,
# and register_event/_reg live in soothe_sdk.core.registry so that nano, the
# host, and the daemon share one authoritative event-type index. nano modules
# register directly into that shared REGISTRY at import time (see the module
# imports below), so no host-side merge loop is required.
from soothe_sdk.core.registry import (  # noqa: E402,F401
    REGISTRY,
    EventHandler,
    EventMeta,
    EventPriority,
    EventRegistry,
    _reg,
    register_event,
)

# -- Lifecycle ---------------------------------------------------------------
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
_reg(LOOP_CREATED, LoopCreatedEvent, summary_template="Loop {loop_id} created")
_reg(LOOP_STARTED, LoopStartedEvent, summary_template="loop={loop_id}")
_reg(LOOP_COMPLETED, LoopCompletedEvent, summary_template="loop={loop_id}")
_reg(
    DAEMON_HEARTBEAT,
    DaemonHeartbeatEvent,
    verbosity=VerbosityTier.INTERNAL,
    summary_template="Daemon heartbeat: state={state}",
)
_reg(
    CONFIG_RELOADED,
    ConfigReloadedEvent,
    verbosity=VerbosityTier.NORMAL,
    summary_template="Config reloaded: {config_type}",
    priority=EventPriority.HIGH,
)

# -- Strange Loop (RFC-0008) -------------------------------------------------
_reg(
    STRANGE_LOOP_STARTED,
    StrangeLoopStartedEvent,
    verbosity=VerbosityTier.NORMAL,
    summary_template="{goal}",
    priority=EventPriority.HIGH,
)
_reg(
    STRANGE_LOOP_COMPLETED,
    StrangeLoopCompletedEvent,
    verbosity=VerbosityTier.NORMAL,
    summary_template="Done: {completion_summary}",
    priority=EventPriority.HIGH,
)
_reg(
    STRANGE_LOOP_PLAN_DECISION,
    StrangeLoopPlanDecisionEvent,
    verbosity=VerbosityTier.NORMAL,
    summary_template="Act plan · {execution_mode}",
    priority=EventPriority.HIGH,
)
_reg(
    STRANGE_LOOP_PLAN_PHASE,
    StrangeLoopPlanPhaseStatusEvent,
    verbosity=VerbosityTier.NORMAL,
    summary_template="{label}",
    priority=EventPriority.HIGH,
)
_reg(
    WIRED_SUBAGENT_STARTED,
    WiredSubagentStartedEvent,
    verbosity=VerbosityTier.NORMAL,
    summary_template="Delegating to {subagent}",
    priority=EventPriority.HIGH,
)
_reg(
    WIRED_SUBAGENT_COMPLETED,
    WiredSubagentCompletedEvent,
    verbosity=VerbosityTier.NORMAL,
    summary_template="{summary}",
    priority=EventPriority.HIGH,
)
_reg(
    WIRED_SUBAGENT_FAILED,
    WiredSubagentFailedEvent,
    verbosity=VerbosityTier.NORMAL,
    summary_template="{summary}",
    priority=EventPriority.HIGH,
)
_reg(
    WIRED_SUBAGENT_CANCELLED,
    WiredSubagentCancelledEvent,
    verbosity=VerbosityTier.NORMAL,
    summary_template="{summary}",
    priority=EventPriority.HIGH,
)
_reg(
    STRANGE_LOOP_STEP_STARTED,
    StrangeLoopStepStartedEvent,
    verbosity=VerbosityTier.NORMAL,  # RFC-0020: Step descriptions visible at normal verbosity
    summary_template="{description}",
    priority=EventPriority.HIGH,
)
_reg(
    STRANGE_LOOP_STEP_QUEUED,
    StrangeLoopStepQueuedEvent,
    verbosity=VerbosityTier.NORMAL,
    summary_template="Queued: {description}",
    priority=EventPriority.HIGH,
)
_reg(
    STRANGE_LOOP_STEP_COMPLETED,
    StrangeLoopStepCompletedEvent,
    verbosity=VerbosityTier.NORMAL,  # Show step completion at normal verbosity for progress visibility
    summary_template="{summary} ({duration_ms}ms)",
    priority=EventPriority.HIGH,
)
_reg(
    STRANGE_LOOP_CONTEXT_COMPACTED,
    StrangeLoopContextCompactionEvent,
    verbosity=VerbosityTier.INTERNAL,
    summary_template="Context compacted: {tokens_before} → {tokens_after} tokens",
    priority=EventPriority.NORMAL,
)

# -- Protocol: plan ----------------------------------------------------------
# Plan display is handled by on_plan_created() renderer, not summary template
_reg(PLAN_CREATED, PlanCreatedEvent)
_reg(
    PLAN_BATCH_STARTED,
    PlanBatchStartedEvent,
    summary_template="Batch: {parallel_count} steps in parallel",
)
_reg(PLAN_REFLECTED, PlanReflectedEvent, summary_template="Reflected: {assessment}")
_reg(PLAN_DAG_SNAPSHOT, PlanDagSnapshotEvent, verbosity=VerbosityTier.INTERNAL)

# -- Protocol: intent --------------------------------------------------------
_reg(
    INTENT_CLASSIFIED,
    IntentClassifiedEvent,
    verbosity=VerbosityTier.NORMAL,
    summary_template="{reasoning}",
    priority=EventPriority.HIGH,
)

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
_reg(GOAL_REMOVED, GoalRemovedEvent, summary_template="Goal {goal_id} removed: {reason}")
_reg(
    GOAL_DECOMPOSED,
    GoalDecomposedEvent,
    summary_template="Goal {parent_goal_id} decomposed into {len(child_goal_ids)} sub-goals",
)
_reg(
    AUTOPILOT_MODE_SWITCHED,
    AutopilotModeSwitchedEvent,
    summary_template="Autopilot mode {'enabled' if enabled else 'disabled'} for loop {loop_id}",
)

# -- Autopilot (RFC-204) -------------------------------------------------


class _BranchCreatedEvent(SootheEvent):
    type: str = "soothe.cognition.branch.created"
    branch_id: str
    iteration: int
    failure_reason: str


class _BranchAnalyzedEvent(SootheEvent):
    type: str = "soothe.internal.branch.analyzed"
    branch_id: str
    avoid_patterns: list[str] = []
    suggested_adjustments: list[str] = []


class _BranchRetryStartedEvent(SootheEvent):
    type: str = "soothe.cognition.branch.retry.started"
    branch_id: str
    retry_iteration: int
    learning_applied: list[str] = []


class _BranchPrunedEvent(SootheEvent):
    type: str = "soothe.internal.branch.pruned"
    branch_id: str
    loop_id: str


_reg(BRANCH_CREATED, _BranchCreatedEvent, verbosity=VerbosityTier.NORMAL)
_reg(BRANCH_ANALYZED, _BranchAnalyzedEvent, verbosity=VerbosityTier.INTERNAL)
_reg(BRANCH_RETRY_STARTED, _BranchRetryStartedEvent, verbosity=VerbosityTier.NORMAL)
_reg(BRANCH_PRUNED, _BranchPrunedEvent, verbosity=VerbosityTier.INTERNAL)


class _AutopilotStatusChanged(SootheEvent):
    type: str = "soothe.system.autopilot.status.changed"
    state: str


class _AutopilotGoalCreated(SootheEvent):
    type: str = "soothe.system.autopilot.goal.created"
    goal_id: str
    description: str = ""


class _AutopilotGoalReported(SootheEvent):
    type: str = "soothe.system.autopilot.goal.reported"
    goal_id: str
    status: str = ""


class _AutopilotGoalCompleted(SootheEvent):
    type: str = "soothe.system.autopilot.goal.completed"
    goal_id: str


class _AutopilotDreamingStarted(SootheEvent):
    type: str = "soothe.system.autopilot.dreaming.started"
    timestamp: str = ""


class _AutopilotDreamingCompleted(SootheEvent):
    type: str = "soothe.system.autopilot.dreaming.completed"
    timestamp: str = ""
    trigger: str = ""


class _AutopilotGoalValidated(SootheEvent):
    type: str = "soothe.internal.autopilot.goal.validated"
    goal_id: str
    confidence: float = 1.0


class _AutopilotGoalSuspended(SootheEvent):
    type: str = "soothe.system.autopilot.goal.suspended"
    goal_id: str
    reason: str = ""


class _AutopilotFeedbackSent(SootheEvent):
    type: str = "soothe.internal.autopilot.feedback.sent"
    goal_id: str
    remaining_budget: int = 0
    feedback: str = ""


class _AutopilotRelationshipDetected(SootheEvent):
    type: str = "soothe.internal.autopilot.relationship.detected"
    from_goal: str
    to_goal: str
    relationship_type: str
    confidence: float = 0.0


class _AutopilotCheckpointSaved(SootheEvent):
    type: str = "soothe.internal.autopilot.checkpoint.saved"
    thread_id: str
    trigger: str = ""


class _AutopilotGoalBlocked(SootheEvent):
    type: str = "soothe.system.autopilot.goal.blocked"
    goal_id: str
    reason: str = ""


_reg(AUTOPILOT_STATUS_CHANGED, _AutopilotStatusChanged, verbosity=VerbosityTier.NORMAL)
_reg(AUTOPILOT_GOAL_CREATED, _AutopilotGoalCreated, verbosity=VerbosityTier.NORMAL)
_reg(AUTOPILOT_GOAL_REPORTED, _AutopilotGoalReported, verbosity=VerbosityTier.NORMAL)
_reg(AUTOPILOT_GOAL_COMPLETED, _AutopilotGoalCompleted, verbosity=VerbosityTier.NORMAL)
_reg(AUTOPILOT_DREAMING_STARTED, _AutopilotDreamingStarted, verbosity=VerbosityTier.NORMAL)
_reg(AUTOPILOT_DREAMING_COMPLETED, _AutopilotDreamingCompleted, verbosity=VerbosityTier.NORMAL)
_reg(AUTOPILOT_GOAL_VALIDATED, _AutopilotGoalValidated, verbosity=VerbosityTier.INTERNAL)
_reg(AUTOPILOT_GOAL_SUSPENDED, _AutopilotGoalSuspended, verbosity=VerbosityTier.NORMAL)
_reg(AUTOPILOT_FEEDBACK_SENT, _AutopilotFeedbackSent, verbosity=VerbosityTier.INTERNAL)
_reg(
    AUTOPILOT_RELATIONSHIP_DETECTED,
    _AutopilotRelationshipDetected,
    verbosity=VerbosityTier.INTERNAL,
)
_reg(AUTOPILOT_CHECKPOINT_SAVED, _AutopilotCheckpointSaved, verbosity=VerbosityTier.INTERNAL)
_reg(AUTOPILOT_GOAL_BLOCKED, _AutopilotGoalBlocked, verbosity=VerbosityTier.NORMAL)


# ---------------------------------------------------------------------------
# Import event modules to trigger self-registration
# These modules call register_event() at import time
# Must be at the end after all core events are registered
# ---------------------------------------------------------------------------

# nano modules register directly into the shared soothe_sdk.core.registry REGISTRY
# at import time, so importing them here is sufficient — no host-side merge needed.
# Ensure nano protocol primitives (stream/memory/policy/ERROR) are registered.
import soothe_nano.events.catalog as _nano_events_catalog  # noqa: F401, E402
import soothe_nano.mcp.mcp_events as _mcp_events  # noqa: F401, E402
import soothe_nano.plugin.events as _plugin_events  # noqa: F401, E402
import soothe_nano.skills.events as _skill_events  # noqa: F401, E402
import soothe_nano.subagents.academic_research.events as _academic_research_events  # noqa: F401, E402
import soothe_nano.subagents.browser_use.events as _browser_use_events  # noqa: F401, E402
import soothe_nano.subagents.deep_research.events as _deep_research_events  # noqa: F401, E402
