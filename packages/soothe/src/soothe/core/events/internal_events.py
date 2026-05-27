"""Internal event types for AL ↔ GE ↔ AP coordination (RFC-222).

This module defines event classes for the `soothe.internal.*` namespace.
These events are used for internal coordination between:
- AgentLoop (Layer 2) - emits goal completion/failure events
- GoalEngine (Layer 3) - owns goal state, dispatches state changes
- AutopilotService (Layer 3) - manages loop pool, scheduling

Key Principle: Internal events never leak to external clients (WebSocket, TUI).

Event Namespaces:
- soothe.internal.goal.* - AL ↔ GE goal coordination
- soothe.internal.loop.* - Loop lifecycle and lineage
- soothe.internal.file.* - File lock conflict resolution
- soothe.internal.autopilot.* - AP lifecycle, worker pool
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import Field
from soothe_sdk.core.events import SootheEvent

# ============================================================================
# soothe.internal.goal.* - AL ↔ GE goal coordination
# ============================================================================


class InternalGoalCompletedEvent(SootheEvent):
    """Goal completed by AgentLoop.

    Emitted by AL when goal execution succeeds. Received by GoalEngine
    to update goal status and release file locks.
    """

    type: str = "soothe.internal.goal.completed"
    goal_id: str
    loop_id: str
    plan_result: dict[str, Any]  # PlanResult serialized
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))


class InternalGoalFailedEvent(SootheEvent):
    """Goal failed by AgentLoop.

    Emitted by AL when goal execution fails. Received by GoalEngine
    for backoff reasoning and DAG restructuring.
    """

    type: str = "soothe.internal.goal.failed"
    goal_id: str
    loop_id: str
    evidence: dict[str, Any]  # EvidenceBundle serialized
    error_message: str | None = None
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))


class InternalGoalProgressEvent(SootheEvent):
    """Goal progress update from AgentLoop.

    Emitted periodically by AL during execution. Used by AP
    for loop health monitoring and progress tracking.
    """

    type: str = "soothe.internal.goal.progress"
    goal_id: str
    loop_id: str
    iteration: int
    phase: Literal["planning", "executing", "reflecting"]
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))


class InternalGoalStateChangedEvent(SootheEvent):
    """Goal state changed by GoalEngine.

    Emitted by GE when goal status transitions. Received by AP
    to re-evaluate scheduling and trigger webhooks.
    """

    type: str = "soothe.internal.goal.state_changed"
    goal_id: str
    old_status: str
    new_status: str
    reason: str | None = None
    loop_id: str | None = None  # If loop was assigned/released
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))


class InternalGoalsReadyEvent(SootheEvent):
    """Goals ready for scheduling.

    Emitted by GE when new goals become ready (deps satisfied, no conflicts).
    Received by AP to trigger scheduling loop.
    """

    type: str = "soothe.internal.goal.ready"
    goal_ids: list[str]
    count: int
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))


# ============================================================================
# soothe.internal.loop.* - Loop lifecycle and lineage
# ============================================================================


class InternalLoopAssignedEvent(SootheEvent):
    """Loop assigned to goal.

    Emitted by AP when loop is assigned to a goal. Used for
    lineage tracking and context preservation.
    """

    type: str = "soothe.internal.loop.assigned"
    loop_id: str
    goal_id: str
    parent_goal_id: str | None = None  # If lineage reuse
    reused: bool = False  # True if reused parent's loop
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))


class InternalLoopIdleEvent(SootheEvent):
    """Loop became idle.

    Emitted by AP when loop finishes goal and waits for assignment.
    Used for idle timeout tracking and loop release.
    """

    type: str = "soothe.internal.loop.idle"
    loop_id: str
    last_goal_id: str
    idle_since: datetime = Field(default_factory=lambda: datetime.now(UTC))
    goal_history_count: int = 0


class InternalLoopReleasedEvent(SootheEvent):
    """Loop released (destroyed).

    Emitted by AP when loop is released after idle timeout or shutdown.
    """

    type: str = "soothe.internal.loop.released"
    loop_id: str
    reason: Literal["idle_timeout", "shutdown", "error"]
    goals_processed: int = 0
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))


class InternalLoopSpawnedEvent(SootheEvent):
    """New loop spawned.

    Emitted by AP when new loop is created for goal execution.
    """

    type: str = "soothe.internal.loop.spawned"
    loop_id: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))


# ============================================================================
# soothe.internal.file.* - File lock conflict resolution
# ============================================================================


class InternalFileLockedEvent(SootheEvent):
    """File locked by AgentLoop.

    Emitted by FileLockMiddleware when file operation is intercepted.
    Received by GE to update file lock registry.
    """

    type: str = "soothe.internal.file.locked"
    goal_id: str
    loop_id: str
    file_path: str
    operation: Literal["edit", "write", "delete"]
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))


class InternalFileReleasedEvent(SootheEvent):
    """File lock released.

    Emitted by GE when goal completes and locks are released.
    """

    type: str = "soothe.internal.file.released"
    goal_id: str
    file_path: str
    loop_id: str | None = None
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))


class InternalFileConflictEvent(SootheEvent):
    """File conflict detected.

    Emitted by FileLockMiddleware when conflicting file operation
    is attempted. AL should handle replan or wait.
    """

    type: str = "soothe.internal.file.conflict"
    goal_id: str
    file_path: str
    blocking_goal_id: str
    blocking_loop_id: str
    operation_attempted: Literal["edit", "write", "delete"]
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))


# ============================================================================
# soothe.internal.autopilot.* - AP lifecycle, worker pool
# ============================================================================


class InternalAutopilotStartedEvent(SootheEvent):
    """Autopilot started.

    Emitted by AutopilotService when entering autopilot mode.
    """

    type: str = "soothe.internal.autopilot.started"
    max_loops: int
    config: dict[str, Any] | None = None
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))


class InternalAutopilotStoppedEvent(SootheEvent):
    """Autopilot stopped.

    Emitted by AutopilotService when exiting autopilot mode.
    """

    type: str = "soothe.internal.autopilot.stopped"
    reason: Literal["user_request", "error", "shutdown", "all_goals_complete"]
    active_loops: int = 0
    goals_completed: int = 0
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))


class InternalLoopPoolChangedEvent(SootheEvent):
    """Loop pool state changed.

    Emitted by AP when loop pool composition changes.
    """

    type: str = "soothe.internal.autopilot.pool_changed"
    active_count: int
    idle_count: int
    total_count: int
    change_type: Literal["spawn", "release", "assign", "idle"]
    loop_id: str | None = None
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))


class InternalAutopilotDreamingEvent(SootheEvent):
    """Autopilot entered dreaming mode.

    Emitted by AP when no goals active and dreaming enabled.
    """

    type: str = "soothe.internal.autopilot.dreaming"
    trigger: Literal["all_goals_complete", "no_ready_goals"]
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))


class InternalAutopilotAwakeEvent(SootheEvent):
    """Autopilot woke from dreaming.

    Emitted by AP when exiting dreaming mode.
    """

    type: str = "soothe.internal.autopilot.awake"
    trigger: Literal["new_task", "wake_signal", "scheduled_task"]
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))


# ============================================================================
# Event type constants for subscription
# ============================================================================

INTERNAL_GOAL_COMPLETED = "soothe.internal.goal.completed"
INTERNAL_GOAL_FAILED = "soothe.internal.goal.failed"
INTERNAL_GOAL_PROGRESS = "soothe.internal.goal.progress"
INTERNAL_GOAL_STATE_CHANGED = "soothe.internal.goal.state_changed"
INTERNAL_GOALS_READY = "soothe.internal.goal.ready"

INTERNAL_LOOP_ASSIGNED = "soothe.internal.loop.assigned"
INTERNAL_LOOP_IDLE = "soothe.internal.loop.idle"
INTERNAL_LOOP_RELEASED = "soothe.internal.loop.released"
INTERNAL_LOOP_SPAWNED = "soothe.internal.loop.spawned"

INTERNAL_FILE_LOCKED = "soothe.internal.file.locked"
INTERNAL_FILE_RELEASED = "soothe.internal.file.released"
INTERNAL_FILE_CONFLICT = "soothe.internal.file.conflict"

INTERNAL_AUTOPILOT_STARTED = "soothe.internal.autopilot.started"
INTERNAL_AUTOPILOT_STOPPED = "soothe.internal.autopilot.stopped"
INTERNAL_LOOP_POOL_CHANGED = "soothe.internal.autopilot.pool_changed"
INTERNAL_AUTOPILOT_DREAMING = "soothe.internal.autopilot.dreaming"
INTERNAL_AUTOPILOT_AWAKE = "soothe.internal.autopilot.awake"


# All internal event types for iteration
INTERNAL_EVENT_TYPES: frozenset[str] = frozenset(
    {
        INTERNAL_GOAL_COMPLETED,
        INTERNAL_GOAL_FAILED,
        INTERNAL_GOAL_PROGRESS,
        INTERNAL_GOAL_STATE_CHANGED,
        INTERNAL_GOALS_READY,
        INTERNAL_LOOP_ASSIGNED,
        INTERNAL_LOOP_IDLE,
        INTERNAL_LOOP_RELEASED,
        INTERNAL_LOOP_SPAWNED,
        INTERNAL_FILE_LOCKED,
        INTERNAL_FILE_RELEASED,
        INTERNAL_FILE_CONFLICT,
        INTERNAL_AUTOPILOT_STARTED,
        INTERNAL_AUTOPILOT_STOPPED,
        INTERNAL_LOOP_POOL_CHANGED,
        INTERNAL_AUTOPILOT_DREAMING,
        INTERNAL_AUTOPILOT_AWAKE,
    }
)


def is_internal_event_type(event_type: str) -> bool:
    """Check if event type is internal.

    Internal events start with "soothe.internal." and should
    not be broadcast to external clients.

    Args:
        event_type: Event type string.

    Returns:
        True if internal event type.
    """
    return event_type.startswith("soothe.internal.") or event_type in INTERNAL_EVENT_TYPES
