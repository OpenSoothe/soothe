"""PlannerProtocol -- goal decomposition and plan lifecycle (RFC-0002 Module 3)."""

from __future__ import annotations

from typing import Any, Literal, Protocol, runtime_checkable

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
        current_activity: Latest activity text for this step (for TUI rendering).
    """

    id: str
    description: str
    execution_hint: Literal["tool", "subagent", "remote", "auto"] = "auto"
    status: Literal["pending", "in_progress", "completed", "failed"] = "pending"
    result: str | None = None
    depends_on: list[str] = Field(default_factory=list)
    current_activity: str | None = None


class Plan(BaseModel):
    """A structured decomposition of a goal into executable steps.

    Args:
        goal: The original goal text.
        steps: Ordered list of plan steps.
        current_index: Index of the current/next step to execute.
        status: Overall plan status.
        concurrency: Parallel execution configuration.
        general_activity: Latest non-step activity (for TUI rendering).
    """

    goal: str
    steps: list[PlanStep]
    current_index: int = 0
    status: Literal["active", "completed", "failed", "revised"] = "active"
    concurrency: ConcurrencyPolicy = Field(default_factory=ConcurrencyPolicy)
    general_activity: str | None = None

    # Unified planning metadata
    is_plan_only: bool = Field(default=False, description="User wants planning without execution")
    reasoning: str | None = Field(default=None, description="Intent classification reasoning")


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
        unified_classification: Pre-computed unified classification (RFC-0012).
    """

    recent_messages: list[str] = Field(default_factory=list)
    available_capabilities: list[str] = Field(default_factory=list)
    completed_steps: list[StepResult] = Field(default_factory=list)
    unified_classification: Any | None = None  # Type: UnifiedClassification


class StepReport(BaseModel):
    """Report from a single executed step (RFC-0009).

    Args:
        step_id: The step that was executed.
        description: Step description.
        status: Final step status.
        result: Output text (truncated).
        duration_ms: Execution time in milliseconds.
        depends_on: IDs of steps this step depended on.
    """

    step_id: str
    description: str
    status: Literal["completed", "failed", "skipped"]
    result: str = ""
    duration_ms: int = 0
    depends_on: list[str] = Field(default_factory=list)


class GoalReport(BaseModel):
    """Aggregate report from a completed goal (RFC-0009, RFC-0010).

    Args:
        goal_id: Goal identifier.
        description: Goal description.
        step_reports: Reports from all steps.
        summary: Synthesized summary of results.
        status: Final goal status.
        duration_ms: Total execution time.
        reflection_assessment: Planner reflection on this goal.
        cross_validation_notes: Cross-validation findings.
    """

    goal_id: str
    description: str
    step_reports: list[StepReport] = Field(default_factory=list)
    summary: str = ""
    status: Literal["completed", "failed"] = "completed"
    duration_ms: int = 0
    reflection_assessment: str = ""
    cross_validation_notes: str = ""


class GoalDirective(BaseModel):
    """A single goal management directive from reflection (RFC-0011).

    Args:
        action: 'create' | 'decompose' | 'adjust_priority' | 'add_dependency' | 'fail' | 'complete'
        goal_id: Target goal ID (for existing goals).
        description: Goal description (for create).
        priority: Priority value (for create/adjust_priority).
        parent_id: Parent goal ID (for decomposition).
        depends_on: Dependency list (for create/add_dependency).
        rationale: Why this directive was issued.
    """

    action: Literal["create", "decompose", "adjust_priority", "add_dependency", "fail", "complete"]
    goal_id: str = ""
    description: str = ""
    priority: int | None = None
    parent_id: str | None = None
    depends_on: list[str] = Field(default_factory=list)
    rationale: str = ""


class GoalContext(BaseModel):
    """Context about goal state for reflection (RFC-0011).

    Args:
        current_goal_id: ID of the goal being executed.
        all_goals: List of all goals in the engine (serialized).
        completed_goals: Goal IDs that have completed.
        failed_goals: Goal IDs that have failed.
        ready_goals: Goal IDs ready for execution.
        max_parallel_goals: Concurrency limit.
    """

    current_goal_id: str
    all_goals: list[dict[str, Any]] = Field(default_factory=list)
    completed_goals: list[str] = Field(default_factory=list)
    failed_goals: list[str] = Field(default_factory=list)
    ready_goals: list[str] = Field(default_factory=list)
    max_parallel_goals: int = 1


class Reflection(BaseModel):
    """Planner's assessment of plan progress (RFC-0010 enhanced, RFC-0011 extended).

    Args:
        assessment: Description of current progress.
        should_revise: Whether the plan needs revision.
        feedback: Specific feedback for revision (if needed).
        blocked_steps: Step IDs blocked by dependency failures.
        failed_details: Map of failed step ID to truncated error output.
        goal_directives: List of goal management actions.
    """

    assessment: str
    should_revise: bool
    feedback: str
    blocked_steps: list[str] = Field(default_factory=list)
    failed_details: dict[str, str] = Field(default_factory=dict)
    goal_directives: list[GoalDirective] = Field(default_factory=list)


class CheckpointEnvelope(BaseModel):
    """Progressive checkpoint for crash recovery (RFC-0010).

    Stored in ``$SOOTHE_HOME/runs/{thread_id}/checkpoint.json`` via
    ``RunArtifactStore.save_checkpoint``.

    Args:
        version: Schema version for forward compatibility.
        timestamp: ISO-8601 checkpoint time.
        mode: Execution mode when checkpoint was created.
        last_query: The user's original query.
        thread_id: Thread identifier.
        goals: GoalEngine snapshot (autonomous mode).
        active_goal_id: Currently executing goal.
        plan: Serialized Plan for the active goal.
        completed_step_ids: Steps already completed in the active plan.
        total_iterations: Iteration counter (autonomous mode).
        status: Whether execution is still in progress.
    """

    version: int = 1
    timestamp: str = ""
    mode: Literal["single_pass", "autonomous"] = "single_pass"
    last_query: str = ""
    thread_id: str = ""
    goals: list[dict[str, Any]] = Field(default_factory=list)
    active_goal_id: str | None = None
    plan: dict[str, Any] | None = None
    completed_step_ids: list[str] = Field(default_factory=list)
    total_iterations: int = 0
    status: Literal["in_progress", "completed", "failed"] = "in_progress"


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

    async def reflect(
        self,
        plan: Plan,
        step_results: list[StepResult],
        goal_context: GoalContext | None = None,
    ) -> Reflection:
        """Evaluate plan progress and recommend goal changes.

        Args:
            plan: The current plan.
            step_results: Results from completed steps.
            goal_context: Optional context about goal state.

        Returns:
            A reflection with assessment, revision recommendation, and goal directives.
        """
        ...
