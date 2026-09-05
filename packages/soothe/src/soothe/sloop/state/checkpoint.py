"""StrangeLoop Checkpoint Models."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from soothe.sloop.state.execution_checkpoint import GoalIndexEntry

_SLOOP_CHECKPOINT_STATUSES = frozenset({"running", "idle", "finalized", "cancelled", "interrupted"})

# Terminal statuses that a loop reaches after any execution path completes.
# Once in a terminal state, the loop will not accept new goals until reset.
_SLOOP_TERMINAL_STATUSES = frozenset({"idle", "finalized", "cancelled"})

# Status to assign to a goal that was interrupted by a fatal_error.
# ``cancelled`` is preferred over ``failed`` because a fatal_error typically
# indicates an infrastructure/execution failure (DB disconnect, step timeout)
# rather than a logic error in the goal itself.
_FATAL_ERROR_GOAL_STATUS: Literal["cancelled", "failed"] = "cancelled"

# Minimum checkpoint schema written/read by current releases (RFC-626 Phase 3).
MIN_SUPPORTED_CHECKPOINT_SCHEMA_VERSION = "5.0"


class WorkingMemoryEntry(BaseModel):
    """One working memory entry."""

    step_id: str
    description: str
    success: bool
    inline_summary: str
    spill_relpath: str | None = None


class WorkingMemoryState(BaseModel):
    """Working memory snapshot."""

    entries: list[WorkingMemoryEntry] = Field(default_factory=list)
    spill_files: list[str] = Field(
        default_factory=list, description="Relative paths to spill files"
    )


# RFC-216: New models for multi-thread lifecycle


class ThreadHealthMetrics(BaseModel):
    """Current thread health state for switching policy evaluation."""

    thread_id: str
    last_updated: datetime

    # Message history metrics
    message_count: int = 0
    estimated_tokens: int = 0
    message_history_size_mb: float = 0.0

    # Execution health
    consecutive_goal_failures: int = 0
    consecutive_rate_limit_errors: int = 0
    last_goal_status: Literal["completed", "failed", "cancelled"] | None = None

    # Checkpoint health
    checkpoint_errors: int = 0
    last_checkpoint_error: str | None = None
    checkpoint_corruption_detected: bool = False

    # Subagent health
    subagent_timeout_count: int = 0
    subagent_crash_count: int = 0
    last_subagent_error: str | None = None

    # Extensible custom metrics
    custom_metrics: dict[str, Any] = Field(default_factory=dict)


class StrangeLoopCheckpoint(BaseModel):
    """Complete StrangeLoop state.

    Includes an `execution_checkpoint` field for schema 5.0. `goal_history`
    is a lightweight index (GoalIndexEntry pattern); goal/step/ledger state is
    recovered from CE persistence on restart.
    """

    # Identity (RFC-216: loop_id independent of thread)
    loop_id: str  # UUID
    # IG-764: no longer a fork-thread history. Holds [main_thread_id] (== loop_id)
    # from initialize(); fork threads are reachable via the checkpointer, not here.
    thread_ids: list[str] = Field(default_factory=list)
    current_thread_id: str  # Active thread (== loop_id per RFC-223)

    # Status (RFC-216: loop-scoped)
    status: Literal["running", "idle", "finalized", "cancelled", "interrupted"]

    # Goal execution history (RFC-216: across all threads)
    # RFC-626 Phase 3: goal_history is now a lightweight index (GoalIndexEntry-like)
    # Goal content recovered from CE GoalNode on restart
    goal_history: list[GoalIndexEntry] = Field(default_factory=list)
    current_goal_index: int = -1  # -1 if no active goal

    # Working memory (cleared per-goal)
    working_memory_state: WorkingMemoryState = Field(default_factory=WorkingMemoryState)

    # Thread health (RFC-216: monitoring)
    thread_health_metrics: ThreadHealthMetrics

    # Loop-level metrics (RFC-216: extended)
    total_goals_completed: int = 0
    total_thread_switches: int = 0
    total_duration_ms: int = 0
    total_tokens_used: int = 0

    # RFC-217 (legacy): goal context injection control. No writer remains; the
    # flag is persisted for schema compatibility and always False.
    thread_switch_pending: bool = False

    # Timestamps
    created_at: datetime
    updated_at: datetime

    # Metadata (informational only, no migration logic)
    schema_version: str = "5.0"  # RFC-626 Phase 3: execution_checkpoint pattern

    # RFC-626 Phase 3: Execution-only checkpoint (optional for backward compat)
    execution_checkpoint: dict[str, Any] | None = Field(
        default=None,
        description="ExecutionCheckpoint fields for schema 5.0 (lazy migration)",
    )

    def force_terminal_status(
        self,
        *,
        terminal_status: Literal["idle", "cancelled", "finalized"] = "idle",
        goal_status: Literal["cancelled", "failed", "completed"] = _FATAL_ERROR_GOAL_STATUS,
        goal_index: int | None = None,
    ) -> bool:
        """Force a running checkpoint into a terminal state (fatal_error handler).

        When `pump_graph` crashes or a graph node sets
        `last_outcome="fatal"`, the runner now emits a wire-visible
        `fatal_error` event, but the checkpoint may still be left
        `status="running"` if the crash bypassed `finalize_goal`.
        This method transitions the loop to a terminal status and marks
        the active goal as cancelled/failed so recovery and
        reconciliation can proceed.

        Args:
            terminal_status: Terminal loop status. Defaults to `idle` so the
                daemon can accept the next goal. Use `cancelled` for hard
                kills (user disconnect, unrecoverable crash).
            goal_status: Status to set on the in-flight goal. Defaults to
                `cancelled` for infrastructure failures.
            goal_index: Index into `goal_history`. When `None`, uses
                `current_goal_index`.

        Returns:
            True if a transition was applied, False if already terminal.
        """
        if self.status in _SLOOP_TERMINAL_STATUSES and terminal_status == self.status:
            return False

        from soothe.sloop.state.status_vocabulary import is_goal_index_in_flight

        idx = goal_index if goal_index is not None else self.current_goal_index
        if idx is not None and 0 <= idx < len(self.goal_history):
            goal = self.goal_history[idx]
            # `awaiting_clarification` is not in-flight (the orphan repair
            # skips it) but must still be terminalizable by the fatal handler.
            if is_goal_index_in_flight(goal.status) or goal.status == "awaiting_clarification":
                goal.status = goal_status  # type: ignore[assignment]
                goal.completed_at = datetime.now(UTC)

        self.status = terminal_status  # type: ignore[assignment]
        self.current_goal_index = -1
        self.updated_at = datetime.now(UTC)

        if self.thread_health_metrics is not None:
            if goal_status == "failed":
                self.thread_health_metrics.consecutive_goal_failures += 1
            self.thread_health_metrics.last_goal_status = goal_status  # type: ignore[assignment]
            self.thread_health_metrics.last_updated = self.updated_at

        return True


_GOAL_INDEX_FIELDS = frozenset(
    {
        "goal_id",
        "thread_id",
        "status",
        "started_at",
        "completed_at",
        "duration_ms",
        "tokens_used",
    }
)


def _strip_enriched_goal_index_fields(item: Any) -> Any:
    """Drop enriched goal content from `goal_history` rows on load."""
    if not isinstance(item, dict):
        return item
    return {k: v for k, v in item.items() if k in _GOAL_INDEX_FIELDS}


def normalize_checkpoint_data(
    data: dict[str, Any],
    *,
    loop_id: str | None = None,
) -> dict[str, Any]:
    """Fill defaults for partial checkpoint blobs stored by daemon registration.

    PostgreSQL `register_loop` / `update_loop_metadata` persist a minimal JSONB
    document for daemon bookkeeping. `StrangeLoopStateManager.load()` expects a
    full `StrangeLoopCheckpoint` schema.

    Supports schema 5.0 `execution_checkpoint` field with lazy migration:
    fills defaults for missing `execution_checkpoint`.
    """
    out = dict(data)
    resolved_loop_id = out.get("loop_id") or loop_id
    if resolved_loop_id:
        out.setdefault("loop_id", resolved_loop_id)

    current_thread_id = out.get("current_thread_id") or ""
    # IG-764: thread_ids holds [main_thread_id] only. Backfill from
    # current_thread_id for legacy blobs that predate the field.
    if not out.get("thread_ids"):
        out["thread_ids"] = [current_thread_id] if current_thread_id else []

    now = datetime.now(UTC)
    out.setdefault("created_at", now)
    out.setdefault("updated_at", out.get("created_at", now))
    out.setdefault("goal_history", [])
    out.setdefault("current_goal_index", -1)
    out.setdefault("working_memory_state", {"entries": [], "spill_files": []})

    if "thread_health_metrics" not in out:
        metrics_thread = current_thread_id or resolved_loop_id or "unknown"
        out["thread_health_metrics"] = {
            "thread_id": metrics_thread,
            "last_updated": out.get("updated_at", now),
        }

    out.setdefault("total_goals_completed", 0)
    out.setdefault("total_thread_switches", 0)
    out.setdefault("total_duration_ms", 0)
    out.setdefault("total_tokens_used", 0)
    out.setdefault("thread_switch_pending", False)

    # Schema version handling (5.0+ only; older blobs are upgraded on read).
    schema_version = out.get("schema_version", MIN_SUPPORTED_CHECKPOINT_SCHEMA_VERSION)
    if schema_version < MIN_SUPPORTED_CHECKPOINT_SCHEMA_VERSION:
        schema_version = MIN_SUPPORTED_CHECKPOINT_SCHEMA_VERSION
    out["schema_version"] = schema_version

    # Strip enriched goal fields from goal_history index rows.
    if out.get("goal_history"):
        out["goal_history"] = [
            _strip_enriched_goal_index_fields(item) for item in out["goal_history"]
        ]

    # RFC-626 Phase 3: execution_checkpoint defaults
    if "execution_checkpoint" not in out:
        out["execution_checkpoint"] = {
            "loop_id": resolved_loop_id or "",
            "thread_id": current_thread_id,
            "iteration": 0,
            "wave_metrics": {},
            "status": "idle",
        }

    status = out.get("status")
    if status not in _SLOOP_CHECKPOINT_STATUSES:
        out["status"] = "idle"
    elif status == "running" and not out.get("goal_history"):
        # Daemon metadata-only row after bind (status=running, no goals yet).
        out["status"] = "idle"
    elif status == "running" and out.get("goal_history"):
        # RFC-626 Phase 4: Defensive recovery for orphaned running loops.
        # A loop stuck in ``running`` on load means the previous execution
        # path crashed before ``finalize_goal`` could transition it to
        # ``idle``. Mark the in-flight goal as cancelled and demote the
        # loop to ``idle`` so the daemon can accept new goals.
        _repair_orphaned_running_loop(out)

    return out


def _repair_orphaned_running_loop(out: dict[str, Any]) -> None:
    """Repair an orphaned `status="running"` checkpoint on load.

    When `pump_graph` crashes before the graph can transition the
    checkpoint to `idle`, the checkpoint is flushed to disk with
    `status="running"` and the active goal stays `running` forever.
    This function marks the active goal as `cancelled` and sets the
    loop status to `idle`. A goal parked for a clarification
    (`awaiting_clarification`) is preserved as-is so the resume flow
    recovers the live LangGraph interrupt.
    """
    from soothe.sloop.state.status_vocabulary import is_goal_index_in_flight

    goal_history = out.get("goal_history") or []
    idx = out.get("current_goal_index", -1)
    repaired = False

    # Coerce to int: deserialized checkpoints may carry current_goal_index as a
    # string (JSON/DB serialization), which would raise
    # ``TypeError: '<=' not supported between instances of 'str' and 'int'``
    # in the comparison below (the d15f incident).
    if isinstance(idx, str):
        try:
            idx = int(idx)
        except ValueError:
            idx = -1

    if idx is not None and 0 <= idx < len(goal_history):
        goal = goal_history[idx]
        if isinstance(goal, dict):
            goal_status = goal.get("status", "")
        else:
            goal_status = getattr(goal, "status", "")

        # A goal parked for a clarification is intentionally paused, not a
        # crashed orphan — preserve running state + the goal index so the
        # resume flow recovers the live LangGraph interrupt.
        if goal_status == "awaiting_clarification":
            # idx is already int-coerced above; write it back so the resume
            # branch sees a clean int (not a JSONB string).
            out["current_goal_index"] = idx
            import logging as _logging

            _logging.getLogger(__name__).info(
                "Preserved loop parked for clarification on load: loop_id=%s goal_index=%s",
                out.get("loop_id", "unknown"),
                idx,
            )
            return

        if is_goal_index_in_flight(goal_status):
            now_iso = datetime.now(UTC).isoformat()
            if isinstance(goal, dict):
                goal["status"] = _FATAL_ERROR_GOAL_STATUS
                goal["completed_at"] = now_iso
            else:
                goal.status = _FATAL_ERROR_GOAL_STATUS  # type: ignore[attr-defined]
                goal.completed_at = datetime.now(UTC)  # type: ignore[attr-defined]
            repaired = True

    out["status"] = "idle"
    out["current_goal_index"] = -1
    out["updated_at"] = datetime.now(UTC).isoformat()

    # Update thread_health_metrics if present
    metrics = out.get("thread_health_metrics")
    if isinstance(metrics, dict):
        metrics["last_goal_status"] = _FATAL_ERROR_GOAL_STATUS
        metrics["last_updated"] = out["updated_at"]
        if _FATAL_ERROR_GOAL_STATUS == "failed":
            metrics["consecutive_goal_failures"] = metrics.get("consecutive_goal_failures", 0) + 1

    if repaired:
        import logging as _logging

        _logger = _logging.getLogger(__name__)
        _logger.warning(
            "Repaired orphaned running loop on load: loop_id=%s, "
            "goal_index=%d marked as %s, loop status -> idle",
            out.get("loop_id", "unknown"),
            idx,
            _FATAL_ERROR_GOAL_STATUS,
        )
