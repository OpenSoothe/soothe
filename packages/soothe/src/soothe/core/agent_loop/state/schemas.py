"""Schemas for AgentLoop execution (RFC-201, IG-153, RFC-214)."""

from __future__ import annotations

import secrets
import uuid
from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

from soothe.config.constants import DEFAULT_AGENT_LOOP_MAX_ITERATIONS
from soothe.core.agent_loop.utils.messages import LoopAIMessage, LoopHumanMessage
from soothe.protocols.planner import planner_outcome_text_preview


class StepAction(BaseModel):
    """Single step in execution strategy.

    IG-264: Keep execution-critical fields (used by executor).

    Attributes:
        id: Step identifier; after plan assembly use stable 3-char ids (``assign_plan_step_ids``).
        description: What this step does
        tools: Tools to use (optional, executor hint)
        subagent: Subagent to invoke (optional, executor hint)
        expected_output: Expected result for evidence accumulation
        dependencies: Step IDs this depends on (for DAG execution)
    """

    id: str = Field(default_factory=lambda: str(uuid.uuid4())[:8])
    description: str = Field(
        ...,
        description="Imperative step; parallel explore passes must name disjoint repo slices.",
    )
    tools: list[str] | None = None
    subagent: str | None = Field(
        default=None,
        description='Optional; use "explore" for readonly workspace search via task tool.',
    )
    expected_output: str = "Step completed successfully"
    dependencies: list[str] | None = None


class AgentDecision(BaseModel):
    """LLM's decision on next action for goal execution.

    Hybrid model: can specify 1 step or N steps.
    IG-264: Keep execution-critical fields (used by planning_utils).

    Attributes:
        type: "execute_steps" or "final"
        steps: Steps to execute (can be 1 or N)
        execution_mode: "parallel", "sequential", or "dependency"
        reasoning: Why these steps advance toward goal (used by planning_utils)
        adaptive_granularity: Step granularity chosen by LLM (used by planning_utils)
    """

    type: Literal["execute_steps", "final"]
    steps: list[StepAction]
    execution_mode: Literal["parallel", "sequential", "dependency"] = Field(
        description="parallel only for independent steps; sequential default; dependency for DAG-ordered work.",
    )
    reasoning: str = ""
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


_STEP_ID_ALPHABET = "abcdefghijklmnopqrstuvwxyz0123456789"
PLAN_STEP_ID_LENGTH = 3


def _allocate_plan_step_id(reserved: set[str]) -> str:
    """Cryptographically random step id (see ``PLAN_STEP_ID_LENGTH``) not in ``reserved``."""
    for _ in range(512):
        candidate = "".join(secrets.choice(_STEP_ID_ALPHABET) for _ in range(PLAN_STEP_ID_LENGTH))
        if candidate not in reserved:
            reserved.add(candidate)
            return candidate
    msg = f"Could not allocate unique {PLAN_STEP_ID_LENGTH}-char step id after 512 attempts"
    raise RuntimeError(msg)


def assign_plan_step_ids(
    decision: AgentDecision,
    *,
    reserved_ids: set[str] | frozenset[str],
) -> AgentDecision:
    """Assign unique 3-character step ids and remap in-plan ``dependencies`` (IG-358).

    New ids never collide with ``reserved_ids`` (typically
    :meth:`LoopState.dependency_completion_ids`) or with each other.
    Dependency edges between steps in this decision are rewritten via an internal
    id map; other dependency strings (e.g. cross-wave ``step_001``) are unchanged
    (IG-346, IG-347).

    Args:
        decision: Parsed or merged execution decision.
        reserved_ids: Step ids that must not be reused (completed work / externals).

    Returns:
        Copy with assigned ids; unchanged if ``steps`` is empty.
    """
    if not decision.steps:
        return decision
    reserved: set[str] = set(reserved_ids)
    id_map: dict[str, str] = {}
    new_steps: list[StepAction] = []
    for step in decision.steps:
        id_map[step.id] = _allocate_plan_step_id(reserved)
    for step in decision.steps:
        mapped = id_map[step.id]
        new_deps: list[str] | None = None
        if step.dependencies:
            new_deps = [id_map.get(dep, dep) for dep in step.dependencies]
        new_steps.append(step.model_copy(update={"id": mapped, "dependencies": new_deps}))
    return decision.model_copy(update={"steps": new_steps})


class PlanResult(BaseModel):
    """Plan phase output with full reasoning chain (RFC-604, IG-152, IG-153).

    Result of the Plan-And-Execute loop's Plan phase, which combines planning,
    progress assessment, and goal-distance estimation in a single structured response.

    Attributes:
        status: Whether to finish, continue current plan, or replan.
        goal_progress: Estimated progress toward the goal (0.0-1.0).
        confidence: Model confidence in the assessment (0.0-1.0).
        assessment_reasoning: Phase-1 status justification (StatusAssessment.brief_reasoning).
        plan_reasoning: Phase-2 plan-strategy text (PlanGeneration.brief_reasoning).
        next_action: User-facing action summary (full text, no truncation).
        full_action: Complete concatenated action from both phases (max 500 chars).
        plan_action: Reuse the in-flight AgentDecision or supply a new one.
        decision: New steps to run when plan_action is new; None when keep.
        evidence_summary: Accumulated evidence text (often filled after parsing).
        full_output: Final user-visible answer when status is done.
        require_goal_completion: Whether extra goal completion LLM call is needed.
            Propagated from StatusAssessment. When False, last AIMessage can be used directly.
    """

    status: Literal["continue", "replan", "done"]
    evidence_summary: str = ""
    goal_progress: float = Field(default=0.0, ge=0.0, le=1.0)
    confidence: float = Field(ge=0.0, le=1.0, default=0.8)

    assessment_reasoning: str = Field(default="", max_length=500)
    """StatusAssessment justification (distinct from plan generation reasoning)."""

    plan_reasoning: str = Field(default="", max_length=500)
    """PlanGeneration strategy justification."""

    next_action: str = Field(default="", max_length=500)
    """Complete action text from both phases (no truncation, full reasoning chain visible)."""

    plan_action: Literal["keep", "new"] = "new"
    decision: AgentDecision | None = None
    full_output: str | None = None

    require_goal_completion: bool = Field(default=False)
    """Dynamic goal completion decision (optimization to skip extra LLM call when not needed)."""

    @model_validator(mode="after")
    def _validate_plan_action(self) -> PlanResult:
        """Ensure keep/new and decision align when status requires execution.

        IG-264: plan_action='keep' CAN have decision (optional, not enforced).
        Only enforce that plan_action='new' requires decision when not done.
        """
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


class StatusAssessment(BaseModel):
    """StatusAssessment: quick progress/status check (RFC-604).

    Lightweight schema for status assessment, generates ~50-80 tokens.
    IG-264: Minimal fields (status, progress, confidence) - 60% token reduction.

    Attributes:
        status: Whether to finish, continue current plan, or replan.
        goal_progress: Estimated progress toward the goal (0.0-1.0).
        confidence: Model confidence in the assessment (0.0-1.0).
        require_goal_completion: Whether an extra goal completion LLM call is needed.
            When False, the last AIMessage from execution can be used as goal completion.
            Only relevant when status="done".
    """

    status: Literal["continue", "replan", "done"]
    goal_progress: float = Field(default=0.0, ge=0.0, le=1.0)
    confidence: float = Field(default=0.8, ge=0.0, le=1.0)
    require_goal_completion: bool = Field(default=False)
    """Dynamic goal completion decision (optimization to skip extra LLM call when not needed)."""


class PlanGeneration(BaseModel):
    """PlanGeneration: generate execution plan when goal incomplete (RFC-604).

    Conditional schema for plan generation, generates ~400-600 tokens.
    IG-264: Keep LLM-generated brief_reasoning and next_action for message variety.

    Attributes:
        plan_action: Reuse in-flight AgentDecision or supply a new one.
        decision: New steps to execute (None when plan_action='keep').
        brief_reasoning: Why this plan strategy was chosen (max 100 chars).
        next_action: User-facing next step (plan-specific, max 300 chars).
    """

    plan_action: Literal["keep", "new"] = "new"
    decision: AgentDecision | None = None

    brief_reasoning: str = Field(default="", max_length=100)
    """Why this plan strategy was chosen (LLM-generated for variety)."""

    next_action: str = Field(default="", max_length=300)
    """User-facing next step (plan-specific, LLM-generated for variety)."""

    @model_validator(mode="after")
    def _validate_plan_action(self) -> PlanGeneration:
        """Ensure keep/new and decision align.

        IG-264: plan_action='keep' CAN have decision (optional, not enforced).
        Only enforce that plan_action='new' requires decision.
        """
        if self.plan_action == "new" and self.decision is None:
            raise ValueError("plan_action 'new' requires decision")
        return self


class StepResult(BaseModel):
    """Result from executing a single step.

    Attributes:
        step_id: ID of the step
        success: Whether execution succeeded
        outcome: Structured metadata from tool execution (RFC-211)
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
    outcome: dict = Field(default_factory=dict)  # RFC-211
    error: str | None = None
    error_type: Literal["execution", "tool", "timeout", "policy", "unknown", "fatal"] | None = None
    duration_ms: int
    thread_id: str
    tool_call_count: int = 0
    subagent_task_completions: int = 0
    hit_subagent_cap: bool = False

    def to_evidence_string(self, *, truncate: bool = True) -> str:
        """Convert to evidence string for judgment.

        Uses outcome metadata to generate concise, informative summaries.

        Args:
            truncate: If True, generate concise summary.
                     If False, return detailed summary for final response.

        Returns:
            Human-readable evidence string
        """
        if not self.success:
            return f"Step {self.step_id}: ✗ Error: {self.error}"

        # Use outcome metadata (RFC-211)
        return self._outcome_to_evidence_string(truncate)

    def get_detailed_evidence_string(self) -> str:
        """Generate detailed evidence with CoreAgent input/output (IG-148).

        Used for Reason phase messages to provide concrete execution
        evidence: what was requested (step_input) and what was found (output_summary).

        Returns:
            Multi-line evidence string with:
            - Step ID and outcome type
            - Input: CoreAgent HumanMessage content (what was requested)
            - Output summary: First 300 + last 200 chars of execution output
            - Entities: Key files/functions/URLs discovered (if available)
        """
        if not self.success:
            return f"Step {self.step_id}: ✗ Error: {self.error}"

        # IG-148: Extract CoreAgent input/output from outcome metadata
        step_input = self.outcome.get("step_input", "")
        output_summary = self.outcome.get("output_summary", {})
        entities = self.outcome.get("entities", [])
        outcome_type = self.outcome.get("type", "unknown")

        # Build detailed evidence string
        lines = [f"Step {self.step_id} [{outcome_type}]:"]

        # Add input (what was requested from CoreAgent)
        if step_input:
            # Truncate very long inputs (show first 150 chars)
            input_preview = step_input[:150] if len(step_input) > 150 else step_input
            lines.append(f"  Input: {input_preview}")

        # Add output summary (concrete findings)
        if output_summary:
            first_part = output_summary.get("first", "")
            last_part = output_summary.get("last", "")

            if first_part:
                lines.append(f"  Output (first): {first_part}")
            if last_part and last_part != first_part:
                lines.append(f"  Output (last): {last_part}")

        # Add entities (key discoveries)
        if entities:
            entity_preview = ", ".join(entities[:5])
            lines.append(f"  Entities: {entity_preview}")

        return "\n".join(lines)

    def _outcome_to_evidence_string(self, truncate: bool) -> str:
        """Generate evidence from outcome metadata.

        Args:
            truncate: Whether to generate concise summary

        Returns:
            Human-readable evidence string based on outcome type
        """
        outcome_type = self.outcome.get("type", "unknown")
        tool_name = self.outcome.get("tool_name", "tool")
        success_indicators = self.outcome.get("success_indicators", {})
        entities = self.outcome.get("entities", [])

        # Tool-specific summaries
        if outcome_type == "file_read":
            lines = success_indicators.get("lines", 0)
            files_found = success_indicators.get("files_found", 0)
            entity_preview = ", ".join(entities[:3]) if entities else "files"

            if truncate:
                return f"Step {self.step_id}: ✓ {tool_name} ({lines} lines, {files_found} files) - {entity_preview}"
            else:
                return f"Step {self.step_id}: ✓ Read {lines} lines from {files_found} files: {entity_preview}"

        elif outcome_type == "file_write":
            files_written = success_indicators.get("files_written", 0)
            entity_preview = ", ".join(entities[:3]) if entities else "files"

            return f"Step {self.step_id}: ✓ {tool_name} ({files_written} files) - {entity_preview}"

        elif outcome_type == "web_search":
            results_count = success_indicators.get("results_count", 0)
            domains = entities[:3] if entities else []

            if truncate:
                return f"Step {self.step_id}: ✓ {tool_name} ({results_count} results)"
            else:
                domain_str = ", ".join(domains) if domains else "various sources"
                return f"Step {self.step_id}: ✓ Found {results_count} results from: {domain_str}"

        elif outcome_type == "code_exec":
            exit_code = success_indicators.get("exit_code", 0)
            stdout_lines = success_indicators.get("stdout_lines", 0)

            status = "success" if exit_code == 0 else f"exit code {exit_code}"
            return f"Step {self.step_id}: ✓ {tool_name} ({status}, {stdout_lines} lines)"

        elif outcome_type == "subagent":
            preview_src = planner_outcome_text_preview(self.outcome)
            tool_name = self.outcome.get("tool_name", "task")
            if preview_src:
                if truncate:
                    prev = preview_src[:800] + ("…" if len(preview_src) > 800 else "")
                else:
                    prev = preview_src
                return f"Step {self.step_id}: ✓ {tool_name} — {prev}"
            completed = success_indicators.get("completed", False)
            artifacts = success_indicators.get("artifacts_created", 0)
            entity_preview = ", ".join(entities[:3]) if entities else "artifacts"

            status = "completed" if completed else "in progress"
            return f"Step {self.step_id}: ✓ Subagent {status} ({artifacts} artifacts) - {entity_preview}"

        else:
            # Generic fallback
            size = self.outcome.get("size_bytes", 0)
            return f"Step {self.step_id}: ✓ {tool_name} (size: {size} bytes)"


class LoopState(BaseModel):
    """State for agentic loop (RFC-201, RFC-214).

    Attributes:
        goal: Goal description
        thread_id: Thread context
        workspace: Thread-specific workspace path (RFC-103)
        git_status: Optional git snapshot for planner prompts (RFC-104)
        iteration: Current iteration number
        max_iterations: Maximum iterations allowed
        current_decision: Current AgentDecision being executed
        completed_step_ids: Set of completed step IDs
        previous_plan: Previous Plan phase result
        step_results: All step results from execution
        evidence_summary: Accumulated evidence summary
        started_at: Loop start timestamp
        total_duration_ms: Total loop duration
        working_memory: Loop working-memory instance (RFC-203) when enabled.
        loop_messages: RFC-214: Unified message ledger with adjacent Human-AI pairs for all orchestration turns.
        last_execute_assistant_text: Resolved visible answer for the latest Execute wave — see
            :mod:`soothe.core.agent_loop.core.act_wave_finalize` (IG-357).
        last_wave_answer_from_delegate_final: True when that text came from ``task`` tool returns
            (``task_tool_aggregate`` provenance), not root-graph assistant stream (IG-355).
        last_execute_wave_parallel_multi_step: True when the last wave ran multiple parallel steps (IG-199).
        thread_continuation: IG-226 flag for thread continuation intent (adjusts iteration behavior).
    """

    goal: str
    thread_id: str
    workspace: str | None = None  # Thread-specific workspace (RFC-103)
    git_status: dict[str, Any] | None = None
    iteration: int = 0
    max_iterations: int = DEFAULT_AGENT_LOOP_MAX_ITERATIONS

    current_decision: AgentDecision | None = None
    completed_step_ids: set[str] = Field(default_factory=set)
    previous_plan: PlanResult | None = None
    step_results: list[StepResult] = []
    evidence_summary: str = ""
    working_memory: Any | None = None

    # RFC-214: Unified message ledger for orchestration turns
    loop_messages: list[LoopHumanMessage | LoopAIMessage] = Field(
        default_factory=list,
        description="Ordered adjacent Human-AI message pairs for all orchestration turns",
    )

    started_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    total_duration_ms: int = 0

    # Last Act wave metrics for Plan prompts (IG-130, IG-132)
    last_wave_tool_call_count: int = 0
    last_wave_subagent_task_count: int = 0
    last_wave_hit_subagent_cap: bool = False
    last_wave_output_length: int = 0
    last_wave_error_count: int = 0
    total_tokens_used: int = 0
    context_percentage_consumed: float = 0.0

    # Action history for progressive specificity tracking (RFC-603)
    action_history: list[str] = Field(
        default_factory=list,
        description="Chronological action descriptions for progression tracking",
    )

    # Last Execute wave assistant text for adaptive final response (IG-199)
    last_execute_assistant_text: str | None = None
    last_wave_answer_from_delegate_final: bool = False
    last_execute_wave_parallel_multi_step: bool = False
    thread_continuation: bool = False  # IG-226: Thread continuation mode flag
    intent: Any | None = None  # IG-268: Intent classification for response length intelligence
    unified_classification: Any | None = None  # IG-349: RoutingClassification for Plan + Execute

    def add_step_result(self, result: StepResult) -> None:
        """Add step result and update completed set.

        Args:
            result: Step execution result
        """
        self.step_results.append(result)
        if result.success:
            self.completed_step_ids.add(result.step_id)

    def dependency_completion_ids(self) -> set[str]:
        """Step IDs that satisfy ``StepAction.dependencies`` edges.

        Combines the current-wave ``completed_step_ids`` with every successful
        ``step_results`` ID. When ``plan_action == 'new'`` clears
        ``completed_step_ids``, replanned steps that still depend on prior-wave
        IDs (e.g. ``step_001``) remain schedulable because historical successes
        stay in ``step_results`` (IG-346).

        Returns:
            Union of completed IDs for dependency checks.
        """
        historical = {r.step_id for r in self.step_results if r.success}
        return self.completed_step_ids | historical

    def add_action_to_history(self, action: str) -> None:
        """Add action description to history for progression tracking.

        Args:
            action: Action description text
        """
        if action and action.strip():
            self.action_history.append(action.strip())

    def get_recent_actions(self, n: int = 3) -> list[str]:
        """Get last N action descriptions.

        Args:
            n: Number of recent actions to retrieve

        Returns:
            List of last N actions (or all if fewer than N)
        """
        return self.action_history[-n:] if self.action_history else []

    def has_remaining_steps(self) -> bool:
        """Check if current decision has remaining steps.

        Returns:
            True if there are remaining steps
        """
        if not self.current_decision:
            return False
        return self.current_decision.has_remaining_steps(self.dependency_completion_ids())
