"""Schemas for Layer 2 Agentic Loop (RFC-0008)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Literal

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


class JudgeResult(BaseModel):
    """LLM's judgment after evaluating goal progress.

    Attributes:
        status: "continue", "replan", or "done"
        evidence_summary: Accumulated from all step results
        goal_progress: Progress toward goal (0.0-1.0)
        confidence: Judge's confidence (0.0-1.0)
        reasoning: Why this judgment was made
        next_steps_hint: Hint for next iteration (optional)
        full_output: Full output for final response (when goal is done)
    """

    status: Literal["continue", "replan", "done"]
    evidence_summary: str
    goal_progress: float = Field(ge=0.0, le=1.0)
    confidence: float = Field(ge=0.0, le=1.0, default=0.8)
    reasoning: str
    next_steps_hint: str | None = None
    full_output: str | None = None

    def should_continue(self) -> bool:
        """Check if loop should continue with current strategy."""
        return self.status == "continue"

    def should_replan(self) -> bool:
        """Check if loop should create new strategy."""
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
    """

    step_id: str
    success: bool
    output: str | None = None
    error: str | None = None
    error_type: Literal["execution", "tool", "timeout", "policy", "unknown"] | None = None
    duration_ms: int
    thread_id: str

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
        iteration: Current iteration number
        max_iterations: Maximum iterations allowed
        current_decision: Current AgentDecision being executed
        completed_step_ids: Set of completed step IDs
        previous_judgment: Previous JUDGE phase result
        step_results: All step results from execution
        evidence_summary: Accumulated evidence summary
        started_at: Loop start timestamp
        total_duration_ms: Total loop duration
    """

    goal: str
    thread_id: str
    iteration: int = 0
    max_iterations: int = 8

    current_decision: AgentDecision | None = None
    completed_step_ids: set[str] = Field(default_factory=set)
    previous_judgment: JudgeResult | None = None
    step_results: list[StepResult] = []
    evidence_summary: str = ""

    started_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    total_duration_ms: int = 0

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
