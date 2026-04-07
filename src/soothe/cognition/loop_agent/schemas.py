"""Schemas for Layer 2 Agentic Loop (RFC-0008)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator


class StepAction(BaseModel):
    """Single step in execution strategy.

    Attributes:
        id: Unique step identifier (8-char hex)
        description: What this step does
        tools: Tools to use (optional)
        subagent: Subagent to invoke (optional)
        expected_output: Expected result for evidence accumulation
        dependencies: Step IDs this depends on (for DAG execution)
    """

    id: str = Field(default_factory=lambda: str(uuid.uuid4())[:8])
    description: str
    tools: list[str] | None = None
    subagent: str | None = None
    expected_output: str
    dependencies: list[str] | None = None


class AgentDecision(BaseModel):
    """LLM's decision on next action for goal execution.

    Hybrid model: can specify 1 step or N steps.

    Attributes:
        type: "execute_steps" or "final"
        steps: Steps to execute (can be 1 or N)
        execution_mode: "parallel", "sequential", or "dependency"
        reasoning: Why these steps advance toward goal
        adaptive_granularity: Step granularity chosen by LLM
    """

    type: Literal["execute_steps", "final"]
    steps: list[StepAction]
    execution_mode: Literal["parallel", "sequential", "dependency"]
    reasoning: str
    adaptive_granularity: Literal["atomic", "semantic"] | None = None

    @model_validator(mode="after")
    def validate_decision(self) -> AgentDecision:
        """Validate that execute_steps has at least one step."""
        if self.type == "execute_steps" and not self.steps:
            raise ValueError("execute_steps requires at least one step")
        return self

    def has_remaining_steps(self, completed_step_ids: set[str]) -> bool:
        """Check if there are steps not yet executed.

        Args:
            completed_step_ids: Set of completed step IDs

        Returns:
            True if there are remaining steps
        """
        return any(s.id not in completed_step_ids for s in self.steps)

    def get_ready_steps(self, completed_step_ids: set[str]) -> list[StepAction]:
        """Get steps ready for execution (dependencies satisfied).

        Args:
            completed_step_ids: Set of completed step IDs

        Returns:
            List of steps ready to execute
        """
        ready = []
        for step in self.steps:
            if step.id in completed_step_ids:
                continue
            if step.dependencies and any(d not in completed_step_ids for d in step.dependencies):
                continue
            ready.append(step)
        return ready


class ReasonResult(BaseModel):
    """Single Reason-phase output: assessment plus optional new plan (ReAct Layer 2).

    Attributes:
        status: Whether to finish, continue current plan, or replan.
        goal_progress: Estimated progress toward the goal (0.0-1.0).
        confidence: Model confidence in the assessment (0.0-1.0).
        reasoning: Internal analysis for tooling/LLM context only - not shown in CLI/TUI.
        user_summary: Short headline for user-facing progress (CLI/TUI).
        soothe_next_action: One first-person sentence as Soothe (e.g. I will / I'll) for the
            immediate next action; primary line in CLI/TUI. Empty when omitted by the model.
        progress_detail: Optional friendly explanation of distance-to-goal.
        plan_action: Reuse the in-flight ``AgentDecision`` or supply a new one.
        decision: New steps to run when ``plan_action`` is ``new``; None when ``keep``.
        evidence_summary: Accumulated evidence text (often filled after parsing).
        next_steps_hint: Optional hint for the next cycle.
        full_output: Final user-visible answer when status is ``done``.
    """

    status: Literal["continue", "replan", "done"]
    evidence_summary: str = ""
    goal_progress: float = Field(default=0.0, ge=0.0, le=1.0)
    confidence: float = Field(ge=0.0, le=1.0, default=0.8)
    reasoning: str = ""
    user_summary: str = ""
    soothe_next_action: str = ""
    progress_detail: str | None = None
    plan_action: Literal["keep", "new"] = "new"
    decision: AgentDecision | None = None
    next_steps_hint: str | None = None
    full_output: str | None = None

    @model_validator(mode="after")
    def _validate_plan_action(self) -> ReasonResult:
        """Ensure keep/new and decision align when status requires execution."""
        if self.plan_action == "keep" and self.decision is not None:
            raise ValueError("plan_action 'keep' requires decision to be None")
        if self.status != "done" and self.plan_action == "new" and self.decision is None:
            raise ValueError("plan_action 'new' requires decision when status is not done")
        return self

    def should_continue(self) -> bool:
        """Check if loop should continue with current strategy."""
        return self.status == "continue"

    def should_replan(self) -> bool:
        """Check if loop should replace the current plan."""
        return self.status == "replan"

    def is_done(self) -> bool:
        """Check if goal is achieved."""
        return self.status == "done"


class StepResult(BaseModel):
    """Result from executing a single step.

    Attributes:
        step_id: ID of the step
        success: Whether execution succeeded
        output: Result output (if successful)
        error: Error message (if failed)
        error_type: Error classification
        duration_ms: Execution duration in milliseconds
        thread_id: Thread used for execution
        tool_call_count: Number of tool calls made during execution
        subagent_task_completions: Completed ``task`` tool results at graph root (IG-130).
        hit_subagent_cap: True when streaming stopped early due to subagent task cap (IG-130).
    """

    step_id: str
    success: bool
    output: str | None = None
    error: str | None = None
    error_type: Literal["execution", "tool", "timeout", "policy", "unknown", "fatal"] | None = None
    duration_ms: int
    thread_id: str
    tool_call_count: int = 0
    subagent_task_completions: int = 0
    hit_subagent_cap: bool = False

    def to_evidence_string(self, *, truncate: bool = True) -> str:
        """Convert to evidence string for judgment.

        Args:
            truncate: If True, truncate output for concise display.
                     If False, return full output for final response.

        Returns:
            Human-readable evidence string
        """
        if self.success:
            output_preview = self.output[:200] if self.output else "no output"
            if not truncate and self.output:
                return self.output
            return f"Step {self.step_id}: ✓ {output_preview}"
        return f"Step {self.step_id}: ✗ Error: {self.error}"


class LoopState(BaseModel):
    """State for Layer 2 agentic loop.

    Attributes:
        goal: Goal description
        thread_id: Thread context
        workspace: Thread-specific workspace path (RFC-103)
        git_status: Optional git snapshot for planner/reason prompts (RFC-104)
        iteration: Current iteration number
        max_iterations: Maximum iterations allowed
        current_decision: Current AgentDecision being executed
        completed_step_ids: Set of completed step IDs
        previous_reason: Previous Reason phase result
        step_results: All step results from execution
        evidence_summary: Accumulated evidence summary
        started_at: Loop start timestamp
        total_duration_ms: Total loop duration
        working_memory: Loop working-memory instance (RFC-203) when enabled.
        reason_conversation_excerpts: Prior Human/Assistant lines for Reason (IG-128).
    """

    goal: str
    thread_id: str
    workspace: str | None = None  # Thread-specific workspace (RFC-103)
    git_status: dict[str, Any] | None = None
    iteration: int = 0
    max_iterations: int = 8

    current_decision: AgentDecision | None = None
    completed_step_ids: set[str] = Field(default_factory=set)
    previous_reason: ReasonResult | None = None
    step_results: list[StepResult] = []
    evidence_summary: str = ""
    working_memory: Any | None = None
    reason_conversation_excerpts: list[str] = Field(default_factory=list)

    started_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    total_duration_ms: int = 0

    # Last Act wave metrics for Reason prompts (IG-130, IG-132)
    last_wave_tool_call_count: int = 0
    last_wave_subagent_task_count: int = 0
    last_wave_hit_subagent_cap: bool = False
    last_wave_output_length: int = 0
    last_wave_error_count: int = 0
    total_tokens_used: int = 0
    context_percentage_consumed: float = 0.0

    # Execution context flag (IG-133): True if Act will load checkpoint history
    act_will_have_checkpoint_access: bool = True

    def add_step_result(self, result: StepResult) -> None:
        """Add step result and update completed set.

        Args:
            result: Step execution result
        """
        self.step_results.append(result)
        if result.success:
            self.completed_step_ids.add(result.step_id)

    def has_remaining_steps(self) -> bool:
        """Check if current decision has remaining steps.

        Returns:
            True if there are remaining steps
        """
        if not self.current_decision:
            return False
        return self.current_decision.has_remaining_steps(self.completed_step_ids)
