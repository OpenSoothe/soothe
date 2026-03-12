"""PlannerProtocol -- goal decomposition and plan lifecycle (RFC-0002 Module 3)."""

from __future__ import annotations

from typing import Literal, Protocol, runtime_checkable

from pydantic import BaseModel, Field

from soothe.protocols.concurrency import ConcurrencyPolicy


class PlanStep(BaseModel):
    """A single step in a plan.

    Args:
        id: Unique step identifier.
        description: What this step should accomplish.
        execution_hint: Preferred execution method.
        status: Current step status.
        result: Output from execution (set after completion).
        depends_on: IDs of steps that must complete before this one.
    """

    id: str
    description: str
    execution_hint: Literal["tool", "subagent", "remote", "auto"] = "auto"
    status: Literal["pending", "in_progress", "completed", "failed"] = "pending"
    result: str | None = None
    depends_on: list[str] = Field(default_factory=list)


class Plan(BaseModel):
    """A structured decomposition of a goal into executable steps.

    Args:
        goal: The original goal text.
        steps: Ordered list of plan steps.
        current_index: Index of the current/next step to execute.
        status: Overall plan status.
        concurrency: Parallel execution configuration.
    """

    goal: str
    steps: list[PlanStep]
    current_index: int = 0
    status: Literal["active", "completed", "failed", "revised"] = "active"
    concurrency: ConcurrencyPolicy = Field(default_factory=ConcurrencyPolicy)


class StepResult(BaseModel):
    """Result of executing a plan step.

    Args:
        step_id: The step that was executed.
        output: The step's output text.
        success: Whether the step succeeded.
        duration_ms: Execution time in milliseconds.
    """

    step_id: str
    output: str
    success: bool
    duration_ms: int | None = None


class PlanContext(BaseModel):
    """Context available to the planner when creating or revising a plan.

    Args:
        recent_messages: Recent conversation messages for context.
        available_capabilities: Names of available tools and subagents.
        completed_steps: Results from already-completed steps.
    """

    recent_messages: list[str] = Field(default_factory=list)
    available_capabilities: list[str] = Field(default_factory=list)
    completed_steps: list[StepResult] = Field(default_factory=list)


class Reflection(BaseModel):
    """Planner's assessment of plan progress.

    Args:
        assessment: Description of current progress.
        should_revise: Whether the plan needs revision.
        feedback: Specific feedback for revision (if needed).
    """

    assessment: str
    should_revise: bool
    feedback: str


@runtime_checkable
class PlannerProtocol(Protocol):
    """Protocol for goal decomposition, plan creation, reflection, and revision."""

    async def create_plan(self, goal: str, context: PlanContext) -> Plan:
        """Decompose a goal into a structured plan.

        Args:
            goal: The goal to decompose.
            context: Available context for planning.

        Returns:
            A structured plan with steps.
        """
        ...

    async def revise_plan(self, plan: Plan, reflection: str) -> Plan:
        """Revise a plan based on reflection feedback.

        Args:
            plan: The current plan.
            reflection: Feedback from the reflection step.

        Returns:
            A revised plan.
        """
        ...

    async def reflect(self, plan: Plan, step_results: list[StepResult]) -> Reflection:
        """Evaluate plan progress and determine if revision is needed.

        Args:
            plan: The current plan.
            step_results: Results from completed steps.

        Returns:
            A reflection with assessment and revision recommendation.
        """
        ...
