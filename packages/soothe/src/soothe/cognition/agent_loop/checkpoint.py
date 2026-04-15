"""AgentLoop Checkpoint Models (RFC-205).

Defines step-level semantic traces for agentic goal execution.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

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


class AgentLoopCheckpoint(BaseModel):
    """Complete AgentLoop state for goal execution."""

    # Identity
    thread_id: str
    goal: str
    created_at: datetime
    updated_at: datetime

    # Execution state
    iteration: int = 0
    max_iterations: int = Field(default=10, description="Maximum loop iterations")
    status: Literal["running", "completed", "failed", "cancelled"] = "running"

    # Reason history (step I/O, not messages)
    reason_history: list[ReasonStepRecord] = Field(default_factory=list)

    # Act history
    act_history: list[ActWaveRecord] = Field(default_factory=list)

    # Working memory state
    working_memory_state: WorkingMemoryState = Field(default_factory=WorkingMemoryState)

    # Metrics
    total_duration_ms: int = 0
    total_tokens_used: int = 0

    schema_version: str = "1.0"
