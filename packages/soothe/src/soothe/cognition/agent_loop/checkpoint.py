"""AgentLoop Checkpoint Models (RFC-205, RFC-608).

Defines step-level semantic traces for agentic goal execution.
RFC-608 extends to multi-thread spanning with infinite lifecycle.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class ToolCallRecord(BaseModel):
    """Tool invocation summary."""

    tool_name: str
    success: bool
    output_preview: str = Field(description="Truncated output (max 200 chars)")


class SubagentCallRecord(BaseModel):
    """Subagent delegation summary."""

    subagent_name: str
    task_input: str
    output_length: int
    success: bool


class StepExecutionRecord(BaseModel):
    """Single step execution with I/O."""

    step_id: str
    description: str

    # Input
    step_input: str = Field(description="Task text sent to execution")

    # Output
    success: bool
    output: str = Field(description="Final result")
    error: str | None = None

    # Tool/subagent metadata
    tool_calls: list[ToolCallRecord] = Field(default_factory=list)
    subagent_calls: list[SubagentCallRecord] = Field(default_factory=list)


class ActWaveRecord(BaseModel):
    """One Act wave execution."""

    iteration: int
    timestamp: datetime

    # Steps executed
    steps: list[StepExecutionRecord] = Field(default_factory=list)

    # Metadata
    execution_mode: Literal["parallel", "sequential", "dependency"]
    duration_ms: int

    # Metrics
    tool_call_count: int = 0
    subagent_task_count: int = 0
    hit_subagent_cap: bool = False
    error_count: int = 0


class ReasonStepRecord(BaseModel):
    """One Reason phase execution."""

    iteration: int
    timestamp: datetime

    # Input
    goal_text: str
    prior_step_outputs: list[str] = Field(
        default_factory=list, description="Derived from previous Act wave outputs"
    )

    # Reasoning
    reasoning: str
    status: Literal["done", "continue", "replan"]
    goal_progress: float

    # Action (IG-152: full text, no truncation)
    next_action: str = Field(default="", description="Complete action text (500 chars)")

    # Decision
    decision: dict | None = Field(description="AgentDecision serialized")


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


# RFC-608: New models for multi-thread lifecycle


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


class CustomSwitchTrigger(BaseModel):
    """Custom thread switching trigger (extensible)."""

    trigger_name: str
    trigger_condition: str
    trigger_threshold: float
    trigger_action: Literal["switch_thread", "alert_user", "log_warning"]


class ThreadSwitchPolicy(BaseModel):
    """Extensible policy for automatic thread switching triggers."""

    # Quantitative triggers
    message_history_token_threshold: int | None = 100000
    consecutive_goal_failure_threshold: int | None = 3
    checkpoint_error_threshold: int | None = 2
    subagent_timeout_threshold: int | None = 2

    # Semantic trigger
    goal_thread_relevance_check_enabled: bool = True
    relevance_analysis_model: str | None = None
    relevance_confidence_threshold: float = 0.7

    # Behavior
    auto_switch_enabled: bool = True
    max_thread_switches_per_loop: int | None = None
    knowledge_transfer_limit: int = 10

    # Custom triggers
    custom_triggers: list[CustomSwitchTrigger] = Field(default_factory=list)

    # Metadata
    policy_name: str = "default"
    policy_version: str = "1.0"


class GoalThreadRelevanceAnalysis(BaseModel):
    """LLM-based analysis of goal-thread relevance."""

    thread_summary: str
    next_goal: str

    # LLM response
    is_relevant: bool
    hindering_reasons: list[str] = Field(default_factory=list)
    confidence: float
    reasoning: str

    # Decision
    should_switch_thread: bool


class GoalExecutionRecord(BaseModel):
    """Single goal execution record (RFC-608: on specific thread)."""

    # Identity (RFC-608: goal_id independent of thread)
    goal_id: str  # "{loop_id}_goal_{seq}"
    goal_text: str
    thread_id: str  # RFC-608: which thread executed this goal

    # Execution state
    iteration: int = 0
    max_iterations: int = 10
    status: Literal["running", "completed", "failed", "cancelled"] = "running"

    # Execution traces
    reason_history: list[ReasonStepRecord] = Field(default_factory=list)
    act_history: list[ActWaveRecord] = Field(default_factory=list)

    # Goal output
    final_report: str = ""
    evidence_summary: str = ""

    # Metrics
    duration_ms: int = 0
    tokens_used: int = 0

    # Timestamps
    started_at: datetime
    completed_at: datetime | None = None


class AgentLoopCheckpoint(BaseModel):
    """Complete AgentLoop state (RFC-608: multi-thread spanning)."""

    # Identity (RFC-608: loop_id independent of thread)
    loop_id: str  # UUID
    thread_ids: list[str] = Field(default_factory=list)  # All threads loop operated on
    current_thread_id: str  # Active thread

    # Status (RFC-608: loop-scoped)
    status: Literal["running", "ready_for_next_goal", "finalized", "cancelled"]

    # Goal execution history (RFC-608: across all threads)
    goal_history: list[GoalExecutionRecord] = Field(default_factory=list)
    current_goal_index: int = -1  # -1 if no active goal

    # Working memory (cleared per-goal)
    working_memory_state: WorkingMemoryState = Field(default_factory=WorkingMemoryState)

    # Thread health (RFC-608: monitoring)
    thread_health_metrics: ThreadHealthMetrics

    # Loop-level metrics (RFC-608: extended)
    total_goals_completed: int = 0
    total_thread_switches: int = 0
    total_duration_ms: int = 0
    total_tokens_used: int = 0

    # Timestamps
    created_at: datetime
    updated_at: datetime

    schema_version: str = "2.0"  # RFC-608: v2.0 for multi-thread
