"""Schemas for AgentLoop execution (RFC-201, IG-153, RFC-214)."""

from __future__ import annotations

import logging
import re
import secrets
import uuid
from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import AliasChoices, BaseModel, Field, model_validator

from soothe.config.constants import DEFAULT_AGENT_LOOP_MAX_ITERATIONS
from soothe.core.agent_loop.utils.messages import LoopAIMessage, LoopHumanMessage
from soothe.protocols.planner import planner_outcome_text_preview

logger = logging.getLogger(__name__)


class EvidenceEntry(BaseModel):
    """Evidence row for plan validation (RFC-620).

    Attributes:
        evidence_id: Stable id referenced by ``StepAction.evidence_refs``.
        summary: Compact summary for prompts and validation.
        kind: Provenance classification.
    """

    evidence_id: str
    summary: str = ""
    kind: Literal["tool", "bootstrap", "ledger"] = "bootstrap"


class StepAction(BaseModel):
    """Single step in execution strategy.

    IG-264: Keep execution-critical fields (used by executor).

    Attributes:
        id: Step identifier; after plan assembly use ``assign_plan_step_ids`` (IG-303: ``<PLANID>-<model-id>``).
        description: What this step does
        subagent: Subagent to invoke (optional, executor hint)
        expected_output: Expected result for evidence accumulation
        supportive_evidence: Which prior ledger facts justify this step (plan-generate; IG-381).
        evidence_refs: Machine-checkable ids into ``LoopState.evidence_ledger`` or prior step ids (RFC-620).
        dependencies: Step IDs this depends on (for DAG execution). Use the same local ``id``
            strings as sibling steps (e.g. ``01``, ``02``); runtime remaps aliases such as ``1`` → ``01``
            when unambiguous (IG-379).
    """

    id: str = Field(default_factory=lambda: str(uuid.uuid4())[:8])
    description: str = Field(
        ...,
        description="Imperative step; parallel explore passes must name disjoint repo slices.",
    )
    subagent: str | None = Field(
        default=None,
        description='Optional; use "explore" for readonly workspace search via task tool.',
    )
    expected_output: str = "Step completed successfully"
    supportive_evidence: str = Field(
        default="",
        max_length=500,
        description="cite execute-ledger evidence this step builds on, or state none yet.",
    )
    evidence_refs: list[str] = Field(
        default_factory=list,
        description="Evidence ids (RFC-620); required when evidence_ledger is non-empty.",
    )
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


PLAN_ID_LENGTH = 3
PLAN_ID_ALPHABET = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"


def composite_step_id(raw_id: str, plan_id: str) -> str:
    """Build scoped step id ``PLAN-MODEL``; idempotent if ``raw_id`` already has this plan prefix (IG-303)."""
    prefix = f"{plan_id}-"
    if raw_id.startswith(prefix):
        return raw_id
    return f"{prefix}{raw_id}"


def _resolve_in_plan_dependency(dep: str, id_map: dict[str, str]) -> str:
    """Map a model dependency string to a scoped in-plan composite id when resolvable.

    Resolution order:
    1. Strip; exact key in ``id_map`` (model local id, e.g. ``01``).
    2. If dependency is all digits, match the unique in-plan step whose ``id`` is all digits and
       has the same integer value (``1`` matches ``01``); if multiple in-plan digit ids collide,
       leave ``dep`` unchanged and log once.
    3. Case-insensitive match against raw step ids when exactly one step matches.

    Otherwise returns ``dep`` unchanged (cross-plan / historical composite refs, IG-346).

    Args:
        dep: Dependency string from the model.
        id_map: Raw step ``id`` → composite ``PLANID-raw`` for the current decision.

    Returns:
        Scoped composite id, or ``dep`` if external / unresolved.
    """
    d = dep.strip()
    if not d:
        return dep
    if d in id_map:
        return id_map[d]
    raw_ids = list(id_map.keys())
    if d.isdigit():
        matches = [rid for rid in raw_ids if rid.isdigit() and int(rid, 10) == int(d, 10)]
        if len(matches) == 1:
            return id_map[matches[0]]
        if len(matches) > 1:
            logger.warning(
                "Ambiguous numeric dependency %r matches in-plan step ids %s; leaving as-is (IG-379)",
                d,
                matches,
            )
            return dep
    lower = d.lower()
    ci_matches = [rid for rid in raw_ids if rid.lower() == lower]
    if len(ci_matches) == 1:
        return id_map[ci_matches[0]]
    return dep


def allocate_plan_id(
    decision: AgentDecision,
    *,
    reserved_step_ids: set[str] | frozenset[str],
) -> str:
    """Allocate a unique uppercase 3-letter plan id so scoped step ids do not collide (IG-303).

    Tries random plan ids until every ``composite_step_id(step.id, plan_id)`` is disjoint
    from ``reserved_step_ids`` and pairwise distinct within ``decision.steps``.

    Args:
        decision: Parsed execution decision (model step ids in ``StepAction.id``).
        reserved_step_ids: Completed or external step ids (e.g. ``dependency_completion_ids()``).

    Returns:
        Three uppercase letters (A–Z).

    Raises:
        RuntimeError: If no plan id is found within the attempt budget.
    """
    if not decision.steps:
        return "".join(secrets.choice(PLAN_ID_ALPHABET) for _ in range(PLAN_ID_LENGTH))
    reserved = set(reserved_step_ids)
    for _ in range(4096):
        plan_id = "".join(secrets.choice(PLAN_ID_ALPHABET) for _ in range(PLAN_ID_LENGTH))
        composites = [composite_step_id(s.id, plan_id) for s in decision.steps]
        if len(set(composites)) != len(composites):
            continue
        if set(composites) & reserved:
            continue
        return plan_id
    msg = f"Could not allocate unique plan id after 4096 attempts ({PLAN_ID_LENGTH}-char A–Z)"
    raise RuntimeError(msg)


def assign_plan_step_ids(
    decision: AgentDecision,
    *,
    plan_id: str,
) -> AgentDecision:
    """Scope model step ids with ``plan_id`` and remap in-plan ``dependencies`` (IG-303).

    Each step becomes ``composite_step_id(step.id, plan_id)``, preserving the model suffix
    (e.g. ``001`` → ``KFA-001``). Dependency edges between steps in this decision are
    rewritten via :func:`_resolve_in_plan_dependency` (exact id, digit-alias, or
    single case-insensitive match); other dependency strings (e.g. cross-wave refs)
    are unchanged (IG-346, IG-379).

    Args:
        decision: Parsed or merged execution decision.
        plan_id: Uppercase plan id from :func:`allocate_plan_id` or inherited ``LoopState.plan_id``.

    Returns:
        Copy with scoped ids; unchanged if ``steps`` is empty.

    Raises:
        ValueError: If two steps collapse to the same composite id after scoping.
    """
    if not decision.steps:
        return decision
    id_map: dict[str, str] = {
        step.id: composite_step_id(step.id, plan_id) for step in decision.steps
    }
    mapped_values = list(id_map.values())
    if len(set(mapped_values)) != len(mapped_values):
        msg = "Plan step ids collapse to duplicate composite ids after scoping"
        raise ValueError(msg)
    new_steps: list[StepAction] = []
    for step in decision.steps:
        mapped = id_map[step.id]
        new_deps: list[str] | None = None
        if step.dependencies:
            new_deps = [_resolve_in_plan_dependency(dep, id_map) for dep in step.dependencies]
        new_steps.append(step.model_copy(update={"id": mapped, "dependencies": new_deps}))
    return decision.model_copy(update={"steps": new_steps})


_STEP_ID_TRAILING_DIGITS = re.compile(r"(\d+)$")


def trailing_numeric_suffix_from_step_id(step_id: str) -> int | None:
    """Parse a positive integer suffix used for goal-continuous step numbering (IG-388).

    Prefer the segment after the last hyphen (``KFA-07`` → 7). If there is no hyphen,
    use the last run of digits (``step_004`` → 4). Returns None when no digits found.

    Args:
        step_id: Scoped or legacy step identifier.

    Returns:
        Parsed non-negative integer, or None when not applicable.
    """
    s = step_id.strip()
    if not s:
        return None
    if "-" in s:
        tail = s.rsplit("-", 1)[-1]
        if tail.isdigit():
            return int(tail, 10)
    m = _STEP_ID_TRAILING_DIGITS.search(s)
    if m:
        return int(m.group(1), 10)
    return None


def max_goal_step_numeric_suffix(state: LoopState) -> int:
    """Largest numeric step suffix seen so far on this goal (IG-388).

    Scans successful/failed ``step_results``, ``completed_step_ids``, and any in-flight
    ``current_decision`` steps so new plans do not reuse lower indices.

    Args:
        state: Active loop state for the goal.

    Returns:
        Maximum parsed suffix, or 0 when none found.
    """
    max_n = 0
    for r in state.step_results:
        n = trailing_numeric_suffix_from_step_id(r.step_id)
        if n is not None:
            max_n = max(max_n, n)
    for sid in state.completed_step_ids:
        n = trailing_numeric_suffix_from_step_id(sid)
        if n is not None:
            max_n = max(max_n, n)
    if state.current_decision:
        for step in state.current_decision.steps:
            n = trailing_numeric_suffix_from_step_id(step.id)
            if n is not None:
                max_n = max(max_n, n)
    return max_n


def next_goal_local_step_id_start(state: LoopState) -> int:
    """Next free 1-based local step index for a new plan wave on this goal (IG-388)."""
    return max_goal_step_numeric_suffix(state) + 1


def _remap_dependency_after_local_renumber(dep: str, old_to_new: dict[str, str]) -> str:
    """Rewrite a dependency string after local id renumber; leave cross-wave refs unchanged."""
    d = dep.strip()
    if not d:
        return dep
    if d in old_to_new:
        return old_to_new[d]
    old_ids = list(old_to_new.keys())
    if d.isdigit():
        matches = [oid for oid in old_ids if oid.isdigit() and int(oid, 10) == int(d, 10)]
        if len(matches) == 1:
            return old_to_new[matches[0]]
    lower = d.lower()
    ci_matches = [oid for oid in old_ids if oid.lower() == lower]
    if len(ci_matches) == 1:
        return old_to_new[ci_matches[0]]
    return dep


def _local_step_token_width(next_start: int, step_count: int) -> int:
    if step_count <= 0:
        return 2
    end = next_start + step_count - 1
    return max(2, len(str(end)))


def renumber_decision_local_step_ids_for_goal_continuation(
    decision: AgentDecision,
    state: LoopState,
) -> AgentDecision:
    """Assign consecutive local step ids starting after the goal's max suffix (IG-388).

    Models often emit ``01``, ``02`` on every plan-generate call; this rewrites new-plan
    steps to ``next``, ``next+1``, … before ``assign_plan_step_ids`` scopes them with
    ``plan_id``. In-plan ``dependencies`` are remapped; other dependency strings are unchanged.

    Args:
        decision: Parsed execution decision from plan-generate (local ids).
        state: Loop state carrying prior step ids for the same goal.

    Returns:
        Copy of ``decision`` with updated step ids and dependencies, or the original when
        there are no steps.
    """
    if not decision.steps:
        return decision
    next_start = next_goal_local_step_id_start(state)
    width = _local_step_token_width(next_start, len(decision.steps))
    old_to_new: dict[str, str] = {}
    for i, step in enumerate(decision.steps):
        new_id = str(next_start + i).zfill(width)
        old_to_new[step.id] = new_id
    new_steps: list[StepAction] = []
    for step in decision.steps:
        mapped = old_to_new[step.id]
        new_deps: list[str] | None = None
        if step.dependencies:
            new_deps = [
                _remap_dependency_after_local_renumber(d, old_to_new) for d in step.dependencies
            ]
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
        assessment_reasoning: Phase-1 status justification (reserved; StatusAssessment has no LLM text field).
        plan_reasoning: Reserved for phase-2 strategy text; not populated from PlanGeneration (IG-329).
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
    """Reserved; assess-phase schema has no separate justification string (IG-329)."""

    plan_reasoning: str = Field(default="", max_length=500)
    """Reserved; plan-generate structured output does not include a separate strategy string (IG-329)."""

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

    Conditional schema for the plan-generate LLM call (IG-329: minimal fields only).

    Attributes:
        plan_action: Reuse in-flight AgentDecision or supply a new one.
        decision: New steps to execute (required when plan_action='new').
        next_action: User-facing next step (plan-specific, max 300 chars).
    """

    plan_action: Literal["keep", "new"] = "new"
    decision: AgentDecision | None = None

    next_action: str = Field(default="", max_length=300)
    """User-facing next step (plan-specific)."""

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
        git_status: Optional git snapshot for planner prompts (branch, main_branch, recent_commits; IG-383)
        iteration: Current iteration number
        max_iterations: Maximum iterations allowed
        current_decision: Current AgentDecision being executed
        plan_id: Active plan scope (3 uppercase letters); new plan allocates, keep reuses (IG-303).
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
    plan_id: str | None = None
    completed_step_ids: set[str] = Field(default_factory=set)
    previous_plan: PlanResult | None = None
    step_results: list[StepResult] = []
    evidence_summary: str = ""
    working_memory: Any | None = None

    evidence_ledger: list[EvidenceEntry] = Field(
        default_factory=list,
        description="Append-only evidence ids for plan validation (RFC-620).",
    )

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
    routing_classification: Any | None = Field(
        default=None,
        validation_alias=AliasChoices("routing_classification", "unified_classification"),
        description="RoutingClassification for Plan + Execute (IG-349, IG-383).",
    )

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
