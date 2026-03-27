"""State models for LoopAgent execution.

This module defines state management across loop iterations:
- StepRecord: Record of a single iteration
- LoopState: Full state maintained across iterations

These models track iteration history, planning state, and layer integration.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from soothe.cognition.loop_agent.core.schemas import (
    AgentDecision,
    JudgeResult,
    ToolOutput,
)


class StepRecord(BaseModel):
    """Record of a single iteration in the agentic loop.

    Each iteration produces a decision, result, and judgment.
    This record enables cross-iteration learning and debugging.

    Attributes:
        step: Iteration number
        decision: LLM's decision (AgentDecision)
        result: Tool execution result (ToolOutput)
        judgment: LLM's judgment (JudgeResult)

    Example:
        >>> record = StepRecord(step=0, decision=AgentDecision(...), result=ToolOutput(...), judgment=JudgeResult(...))
    """

    step: int = Field(..., ge=0, description="Iteration number")
    decision: AgentDecision = Field(..., description="LLM's decision")
    result: ToolOutput = Field(..., description="Tool execution result")
    judgment: JudgeResult = Field(..., description="LLM's judgment")


class LoopState(BaseModel):
    """State maintained across agentic loop iterations.

    The loop state tracks:
    - Current goal
    - Iteration count
    - Full history of decisions/results/judgments
    - Optional high-level plan (if using PlanAgent)
    - Layer 3 integration (goal tracking)

    This state is NOT persisted across sessions (memory is
    handled separately by MemAgent).

    Attributes:
        goal: Task description
        iteration: Current iteration count
        history: List of step records
        plan: Optional high-level plan (from PlanAgent)
        planning_strategy: Planning strategy ("none", "lightweight", "comprehensive")
        current_step_id: Current plan step being executed
        parent_goal_id: Parent goal ID (if from Layer 3)
        current_goal_id: Current goal ID (if from Layer 3)

    Example:
        >>> state = LoopState(goal="Count lines in /tmp/test.txt", iteration=0, history=[])
    """

    # Goal context
    goal: str = Field(..., description="Task description")
    parent_goal_id: str | None = Field(None, description="Parent goal ID if from Layer 3")
    current_goal_id: str | None = Field(None, description="Current goal ID if from Layer 3")

    # Planning state
    plan: Any | None = Field(None, description="Current execution plan from planner")
    planning_strategy: Literal["none", "lightweight", "comprehensive"] = Field(
        "none", description="Planning strategy determined by classifier"
    )

    # Iteration state
    iteration: int = Field(0, ge=0, description="Current iteration count")
    history: list[StepRecord] = Field(default_factory=list, description="Step records")

    # Planning-tracker integration
    current_step_id: str | None = Field(None, description="Current plan step being executed")

    def add_step(self, decision: AgentDecision, result: ToolOutput, judgment: JudgeResult) -> None:
        """Add a step record to history.

        Args:
            decision: LLM's decision
            result: Tool execution result
            judgment: LLM's judgment
        """
        record = StepRecord(
            step=self.iteration,
            decision=decision,
            result=result,
            judgment=judgment,
        )
        self.history.append(record)
        self.iteration += 1

    def get_last_decision(self) -> AgentDecision | None:
        """Get the most recent decision."""
        if not self.history:
            return None
        return self.history[-1].decision

    def get_last_result(self) -> ToolOutput | None:
        """Get the most recent tool result."""
        if not self.history:
            return None
        return self.history[-1].result

    def get_last_judgment(self) -> JudgeResult | None:
        """Get the most recent judgment."""
        if not self.history:
            return None
        return self.history[-1].judgment

    def get_tool_calls(self) -> list[str]:
        """Get list of all tool names called."""
        return [record.decision.tool for record in self.history if record.decision.is_tool_call()]

    def get_errors(self) -> list[str]:
        """Get list of all error messages."""
        return [record.result.error for record in self.history if record.result.error is not None]
