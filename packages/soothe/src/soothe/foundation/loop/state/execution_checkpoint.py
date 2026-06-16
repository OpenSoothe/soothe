"""ExecutionCheckpoint and WaveMetrics for RFC-626 Phase 3.

Execution-only checkpoint fields that ContextEngine does not track.
Goal/step/ledger state is recovered from CE persistence on restart.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, Field

from soothe.config.constants import DEFAULT_STRANGE_LOOP_MAX_ITERATIONS


class WaveMetrics(BaseModel):
    """Wave execution metrics for Plan phase decisions (RFC-626 §1).

    Extracted from LoopState wave fields. These metrics track execution
    performance but are not goal-level state (CE owns that).

    Attributes:
        wave_index: 0-based wave within current iteration.
        tool_call_count: Tool calls in last Execute wave.
        subagent_task_count: Subagent tasks in last Execute wave.
        hit_subagent_cap: Whether last wave hit subagent task cap.
        hit_tool_budget: Whether last wave hit tool budget limit.
        output_length: Character length of last wave output.
        error_count: Errors in last Execute wave.
        tokens_used: Tokens used in last wave.
        duration_ms: Duration of last wave in milliseconds.
        parallel_multi_step: True when last wave ran multiple parallel steps.
        assistant_text: Resolved visible answer for latest Execute wave.
        answer_from_delegate_final: True when assistant_text came from task tool returns.
    """

    wave_index: int = Field(default=0, ge=0, description="0-based wave within current iteration")

    tool_call_count: int = Field(default=0, ge=0, description="Tool calls in last Execute wave")
    subagent_task_count: int = Field(
        default=0, ge=0, description="Subagent tasks in last Execute wave"
    )
    hit_subagent_cap: bool = Field(
        default=False, description="Whether last wave hit subagent task cap"
    )
    hit_tool_budget: bool = Field(
        default=False, description="Whether last wave hit tool budget limit"
    )

    output_length: int = Field(default=0, ge=0, description="Character length of last wave output")
    error_count: int = Field(default=0, ge=0, description="Errors in last Execute wave")
    tokens_used: int = Field(default=0, ge=0, description="Tokens used in last wave")
    duration_ms: int = Field(default=0, ge=0, description="Duration of last wave in milliseconds")

    parallel_multi_step: bool = Field(
        default=False, description="True when last wave ran multiple parallel steps"
    )

    assistant_text: str | None = Field(
        default=None,
        max_length=2000,
        description="Resolved visible answer for latest Execute wave",
    )
    answer_from_delegate_final: bool = Field(
        default=False,
        description="True when assistant_text came from task tool returns (IG-355)",
    )


class ExecutionCheckpoint(BaseModel):
    """Execution-only checkpoint for StrangeLoop recovery (RFC-626 Phase 3).

    Per RFC-626 §4: ExecutionCheckpoint stores execution-only fields,
    not goal-level state (description, steps, ledger). GoalNode state
    is recovered from CE persistence on restart.

    This checkpoint is designed for recovery from crash/interrupt:
    - CE.load() restores GoalStepDAG (goals, steps, ledger)
    - ExecutionCheckpoint restores execution context (iteration, wave metrics)
    - Combined state allows Plan-Execute loop to resume seamlessly

    Attributes:
        loop_id: Loop identifier (UUID, primary key).
        current_goal_id: Current goal being executed (CE lookup key).
        max_iterations: Maximum iterations allowed (config, not CE state).
        iteration: Current iteration number (1-indexed).
        wave_metrics: Last wave execution metrics.
        thread_id: Thread identifier for this goal execution.
        worker_id: Assigned worker loop_id if executing (RFC-222).
        status: Loop status (running, idle, finalized, cancelled).
        thread_switch_pending: Flag for thread switch goal context injection.
        total_goals_completed: Total goals completed in this loop.
        total_thread_switches: Total thread switches in this loop.
        total_duration_ms: Cumulative execution duration in milliseconds.
        total_tokens_used: Cumulative token usage across all goals.
        created_at: Checkpoint creation timestamp.
        updated_at: Last checkpoint update timestamp.
        schema_version: Checkpoint schema version for compatibility.
    """

    # Identity
    loop_id: str = Field(description="Loop identifier (UUID, primary key)")
    current_goal_id: str | None = Field(
        default=None, description="Current goal being executed (CE lookup key)"
    )

    # Execution state (NOT in CE entity model)
    max_iterations: int = Field(
        default=DEFAULT_STRANGE_LOOP_MAX_ITERATIONS,
        ge=1,
        description="Maximum iterations allowed (config, not CE state)",
    )
    iteration: int = Field(default=0, ge=0, description="Current iteration number")

    # Wave metrics
    wave_metrics: WaveMetrics = Field(
        default_factory=WaveMetrics, description="Last wave execution metrics"
    )

    # Thread/worker assignment
    thread_id: str = Field(description="Thread identifier for this goal execution")
    worker_id: str | None = Field(
        default=None, description="Assigned worker loop_id if executing (RFC-222)"
    )

    # Loop status
    status: Literal["running", "idle", "finalized", "cancelled"] = Field(
        default="idle", description="Loop status"
    )
    thread_switch_pending: bool = Field(
        default=False,
        description="Flag indicating thread just switched, Execute needs goal briefing (RFC-217)",
    )

    # Loop-level cumulative metrics
    total_goals_completed: int = Field(
        default=0, ge=0, description="Total goals completed in this loop"
    )
    total_thread_switches: int = Field(
        default=0, ge=0, description="Total thread switches in this loop"
    )
    total_duration_ms: int = Field(
        default=0, ge=0, description="Cumulative execution duration in milliseconds"
    )
    total_tokens_used: int = Field(
        default=0, ge=0, description="Cumulative token usage across all goals"
    )

    # Timestamps
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC), description="Checkpoint creation timestamp"
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC), description="Last checkpoint update timestamp"
    )

    # Schema version
    schema_version: str = Field(
        default="5.0", description="Checkpoint schema version for compatibility"
    )

    def touch(self) -> None:
        """Update updated_at timestamp to current time."""
        self.updated_at = datetime.now(UTC)

    def is_terminal(self) -> bool:
        """Check if loop is in a terminal state.

        Returns:
            True if loop status is finalized or cancelled.
        """
        return self.status in ("finalized", "cancelled")

    def sync_iteration(self, iteration: int) -> None:
        """Sync iteration count from execution state.

        Args:
            iteration: Current iteration number from LoopState.
        """
        self.iteration = iteration
        self.touch()

    def sync_wave_metrics(
        self,
        wave_index: int,
        tool_call_count: int,
        subagent_task_count: int,
        hit_subagent_cap: bool,
        hit_tool_budget: bool,
        output_length: int,
        error_count: int,
        tokens_used: int,
        duration_ms: int,
        parallel_multi_step: bool,
        assistant_text: str | None,
        answer_from_delegate_final: bool,
    ) -> None:
        """Sync wave metrics from execution state after Execute wave.

        Args:
            wave_index: 0-based wave within iteration.
            tool_call_count: Tool calls in this wave.
            subagent_task_count: Subagent tasks in this wave.
            hit_subagent_cap: Whether wave hit subagent cap.
            hit_tool_budget: Whether wave hit tool budget.
            output_length: Character length of output.
            error_count: Errors in this wave.
            tokens_used: Tokens used in this wave.
            duration_ms: Duration of wave in milliseconds.
            parallel_multi_step: True when multiple parallel steps ran.
            assistant_text: Last wave assistant answer text.
            answer_from_delegate_final: True if from task tool returns.
        """
        self.wave_metrics = WaveMetrics(
            wave_index=wave_index,
            tool_call_count=tool_call_count,
            subagent_task_count=subagent_task_count,
            hit_subagent_cap=hit_subagent_cap,
            hit_tool_budget=hit_tool_budget,
            output_length=output_length,
            error_count=error_count,
            tokens_used=tokens_used,
            duration_ms=duration_ms,
            parallel_multi_step=parallel_multi_step,
            assistant_text=assistant_text,
            answer_from_delegate_final=answer_from_delegate_final,
        )
        self.touch()


class GoalIndexEntry(BaseModel):
    """Minimal goal index entry for checkpoint (RFC-626 Phase 3).

    Goal state recovered from CE GoalNode. Checkpoint only stores
    goal_id and status for loop-level tracking.

    Per RFC-626 §4: GoalIndexEntry is a trimmed version of GoalExecutionRecord
    that excludes goal content fields (goal_text, plan_revision_count, goal_completion).
    CE GoalNode is the authoritative source for goal state.

    Attributes:
        goal_id: Goal identifier (CE lookup key, 8-char hex).
        status: Goal execution status.
        thread_id: Thread that executed this goal.
        started_at: Goal start timestamp.
        completed_at: Goal completion timestamp (None if running).
        duration_ms: Goal execution duration in milliseconds.
        tokens_used: Tokens used for this goal.
    """

    # Identity (CE lookup key)
    goal_id: str = Field(description="Goal identifier (CE lookup key)")

    # Status (for loop-level tracking, CE GoalNode has full status)
    status: Literal["running", "completed", "failed", "cancelled"] = Field(
        default="running", description="Goal execution status"
    )

    # Thread assignment (for metrics, not goal content)
    thread_id: str = Field(description="Thread that executed this goal")

    # Timestamps (for metrics only)
    started_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC), description="Goal start timestamp"
    )
    completed_at: datetime | None = Field(
        default=None, description="Goal completion timestamp (None if running)"
    )

    # Metrics (execution-level, not goal content)
    duration_ms: int = Field(default=0, ge=0, description="Goal execution duration in milliseconds")
    tokens_used: int = Field(default=0, ge=0, description="Tokens used for this goal")
