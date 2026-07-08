"""Schemas for StrangeLoop execution (RFC-201, IG-153, RFC-214)."""

from __future__ import annotations

import logging
import re
import secrets
import uuid
from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, PrivateAttr, model_validator

from soothe.config.constants import DEFAULT_STRANGE_LOOP_MAX_ITERATIONS
from soothe.foundation.sloop.utils.messages import LoopAIMessage, LoopHumanMessage
from soothe.foundation.sloop.utils.outcome_preview import planner_outcome_text_preview

logger = logging.getLogger(__name__)

ExecutionMode = Literal["parallel", "dependency"]
"""Planner/executor execution mode for step waves."""

_BUILTIN_WIRE_SUBAGENTS = frozenset(
    {
        "planner",
        "browser_use",
        "deep_research",
    }
)


def resolve_wire_subagent(
    *,
    wire_subagent: str | None = None,
) -> str | None:
    """Return wired subagent name when Pass 2 intake named one explicitly."""
    name = (wire_subagent or "").strip()
    if name and name in _BUILTIN_WIRE_SUBAGENTS:
        return name
    return None


class EvidenceEntry(BaseModel):
    """Evidence row for plan validation (RFC-220).

    Attributes:
        evidence_id: Stable id for the evidence ledger.
        summary: Compact summary for prompts and validation.
        kind: Provenance classification.
    """

    evidence_id: str
    summary: str = ""
    kind: Literal["tool", "bootstrap", "ledger"] = "bootstrap"


StepKind = Literal["action", "ask_user"]
"""Step kind. ``action`` runs through CoreAgent; ``ask_user`` short-circuits
into the clarification relay (RFC-622, IG-462)."""


class PlanGenerateStep(BaseModel):
    """Single step in plan-generate structured output (RFC-604, IG-329, IG-508).

    Separate from ``StepAction`` so the LLM schema omits executor-only fields
    (``subagent``, ``evidence_refs``). Converted to ``StepAction`` when building
    ``AgentDecision``.

    When ``kind == "ask_user"`` the executor does NOT invoke CoreAgent for this
    step — instead it routes ``questions`` through the configured
    ``ClarificationPolicy`` (RFC-622) and records a synthesized successful step
    result containing the answers.

    Attributes:
        id: Step identifier (auto-generated if omitted).
        description: Brief summary for TUI display and logging (under 20 words).
        full_description: Detailed execution prompt with key inputs, file paths,
            identifiers, and context needed to execute independently (IG-508).
        expected_output: Expected result for evidence accumulation.
        dependencies: Step IDs this depends on (for DAG execution).
        continues_from: Completed composite step ids from prior plan waves (merged into dependencies).
        kind: ``action`` (normal) or ``ask_user`` (clarification relay).
        questions: Questions for ``ask_user`` steps.
        execution_hint: Preferred execution routing from the planner.
        subagent: Subagent name when ``execution_hint='subagent'`` (e.g. ``deep_research``).
    """

    id: str = Field(default_factory=lambda: str(uuid.uuid4())[:8])
    description: str = Field(
        ...,
        description="Brief summary for TUI display (under 20 words).",
    )
    full_description: str | None = Field(
        default=None,
        description="Detailed execution prompt with key inputs (50-150 words).",
    )
    expected_output: str = "Step completed successfully"
    dependencies: list[str] | None = None
    continues_from: list[str] | None = Field(
        default=None,
        description="Completed composite step ids from prior plan waves.",
    )
    kind: StepKind = "action"
    questions: list[str] | None = None
    execution_hint: Literal["tool", "subagent", "remote", "auto"] = "auto"
    subagent: str | None = None

    @model_validator(mode="after")
    def _validate_ask_user(self) -> PlanGenerateStep:
        if self.kind == "ask_user" and not self.questions:
            msg = "ask_user step requires non-empty questions"
            raise ValueError(msg)
        return self


def resolve_step_wire_subagent(
    *,
    execution_hint: Literal["tool", "subagent", "remote", "auto"] = "auto",
    subagent: str | None = None,
) -> str | None:
    """Map planner execution hints to executor subagent wiring."""
    if execution_hint != "subagent":
        return None
    name = (subagent or "").strip()
    if not name:
        logger.debug("subagent execution_hint without subagent name; using direct tools")
        return None
    if name not in _BUILTIN_WIRE_SUBAGENTS:
        logger.debug(
            "Ignoring invalid planner subagent %r; using direct tools",
            name,
        )
        return None
    return name


def apply_step_wire_subagents(steps: list[StepAction]) -> list[StepAction]:
    """Attach ``wire_subagent`` on steps that delegate via the planner."""
    out: list[StepAction] = []
    for step in steps:
        wire = resolve_step_wire_subagent(
            execution_hint=step.execution_hint,
            subagent=step.subagent,
        )
        if wire == step.wire_subagent:
            out.append(step)
        else:
            out.append(step.model_copy(update={"wire_subagent": wire}))
    return out


def _merged_step_dependencies(step: PlanGenerateStep) -> list[str] | None:
    """Merge in-wave dependencies and cross-wave continues_from tokens."""
    deps: list[str] = []
    seen: set[str] = set()
    for token in list(step.dependencies or []) + list(step.continues_from or []):
        t = token.strip()
        if not t or t in seen:
            continue
        deps.append(t)
        seen.add(t)
    return deps or None


def plan_generate_steps_to_step_actions(steps: list[PlanGenerateStep]) -> list[StepAction]:
    """Convert plan-generate steps into runtime ``StepAction`` rows."""
    return apply_step_wire_subagents(
        [
            StepAction(
                id=s.id,
                description=s.description,
                full_description=s.full_description,
                expected_output=s.expected_output,
                dependencies=_merged_step_dependencies(s),
                kind=s.kind,
                questions=list(s.questions) if s.questions else None,
                execution_hint=s.execution_hint,
                subagent=s.subagent,
                wire_subagent=resolve_step_wire_subagent(
                    execution_hint=s.execution_hint,
                    subagent=s.subagent,
                ),
            )
            for s in steps
        ]
    )


def step_actions_to_plan_generate_steps(steps: list[StepAction]) -> list[PlanGenerateStep]:
    """Convert runtime steps into plan-generate schema rows (fallback paths)."""
    return [
        PlanGenerateStep(
            id=s.id,
            description=s.description,
            full_description=s.full_description,
            expected_output=s.expected_output,
            dependencies=s.dependencies,
            continues_from=None,
            kind=s.kind,
            questions=list(s.questions) if s.questions else None,
            execution_hint=s.execution_hint,
            subagent=s.subagent,
        )
        for s in steps
    ]


class StepAction(BaseModel):
    """Single step in execution strategy.

    IG-264: Keep execution-critical fields (used by executor).
    IG-508: ``full_description`` carries detailed execution context.
    RFC-622 / IG-462: ``kind`` and ``questions`` carry planner-emitted
    ``ask_user`` steps through to the clarification relay.

    Attributes:
        id: Step identifier; after plan assembly use ``assign_plan_step_ids`` (IG-303: ``<PLANID>-<model-id>``).
        description: Brief summary for TUI display and logging (under 20 words).
        full_description: Detailed execution prompt with key inputs, file paths,
            identifiers, and context needed to execute independently (IG-508).
        expected_output: Expected result for evidence accumulation.
        dependencies: Step IDs this depends on (for DAG execution).
        kind: ``action`` (normal CoreAgent execution) or ``ask_user``
            (clarification relay short-circuit).
        questions: When ``kind == "ask_user"``, the questions to surface to
            the user (TUI manual mode) or veritas (auto mode).
        execution_hint: Planner routing hint (``subagent`` → delegate via ``task``).
        subagent: Named subagent when ``execution_hint='subagent'``.
        wire_subagent: Resolved executor hint (from planner or wire routing).
        requires_tool_use: When set, execute deliverable gate requires successful tool use
            (from Pass 2 intake for trivial steps).
    """

    id: str = Field(default_factory=lambda: str(uuid.uuid4())[:8])
    description: str = Field(
        ...,
        description="Brief summary for TUI display (under 20 words).",
    )
    full_description: str | None = Field(
        default=None,
        description="Detailed execution prompt with key inputs (50-150 words).",
    )
    expected_output: str = "Step completed successfully"
    dependencies: list[str] | None = None
    kind: StepKind = "action"
    questions: list[str] | None = None
    execution_hint: Literal["tool", "subagent", "remote", "auto"] = "auto"
    subagent: str | None = None
    wire_subagent: str | None = None
    requires_tool_use: bool | None = None

    @model_validator(mode="after")
    def _validate_ask_user(self) -> StepAction:
        if self.kind == "ask_user" and not self.questions:
            msg = "ask_user step requires non-empty questions"
            raise ValueError(msg)
        return self


class AgentDecision(BaseModel):
    """LLM's decision on next action for goal execution.

    Hybrid model: can specify 1 step or N steps.
    IG-264: Keep execution-critical fields (used by planning_utils).

    Attributes:
        type: "execute_steps" or "final"
        steps: Steps to execute (can be 1 or N)
        execution_mode: ``parallel`` (default) or ``dependency`` when steps have dependencies
        reasoning: Why these steps advance toward goal (used by planning_utils)
        adaptive_granularity: Step granularity chosen by LLM (used by planning_utils)
    """

    type: Literal["execute_steps", "final"]
    steps: list[StepAction]
    execution_mode: ExecutionMode = Field(
        default="parallel",
        description=(
            "Execute routing: 'parallel' (default) or 'dependency' when steps use dependencies. "
            "Never 'sequential'."
        ),
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
        from soothe.foundation.context.dag_utils import (
            expand_dependency_satisfaction_ids,
        )

        done = expand_dependency_satisfaction_ids(completed_step_ids)
        return any(s.id not in done for s in self.steps)

    def get_ready_steps(self, completed_step_ids: set[str]) -> list[StepAction]:
        """Get steps ready for execution (dependencies satisfied).

        Uses :func:`~soothe.foundation.context.dag_utils.expand_dependency_satisfaction_ids`
        so model-local dependency tokens (e.g. ``01``) match prior-wave composite ids
        (e.g. ``KFA-01``) when unambiguous, consistent with the unified plan DAG (IG-400).

        Args:
            completed_step_ids: Set of completed step IDs

        Returns:
            List of steps ready to execute
        """
        from soothe.foundation.context.dag_utils import (
            expand_dependency_satisfaction_ids,
        )

        done = expand_dependency_satisfaction_ids(completed_step_ids)
        ready = []
        for step in self.steps:
            if step.id in done:
                continue
            if step.dependencies and any(d not in done for d in step.dependencies):
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
        step_id: Step identifier (may include scope prefix).

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

    IG-399: Descriptive progress levels instead of numeric, removed confidence field.

    Attributes:
        status: Whether to finish, continue current plan, or replan.
        goal_progress: Descriptive progress level (none | low | medium | high | complete).
        assessment_reasoning: Phase-1 status justification (reserved; StatusAssessment has no LLM text field).
        plan_reasoning: Plan-generate ``reasoning`` for user-facing cognition cards.
        next_action: Internal orchestration hint (not shown in TUI).
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
    goal_progress: Literal["none", "low", "medium", "high", "complete"] = "none"
    """Descriptive progress level inherited from assessment (IG-399)."""

    assessment_reasoning: str = Field(default="", max_length=500)
    """Reserved; assess-phase schema has no separate justification string (IG-329)."""

    plan_reasoning: str = Field(default="", max_length=500)
    """Plan-generate reasoning surfaced in cognition cards."""

    next_action: str = Field(default="", max_length=500)
    """Internal next-step hint for loop orchestration (not forwarded to TUI)."""

    plan_action: Literal["keep", "new"] = "new"
    decision: AgentDecision | None = None
    full_output: str | None = None

    require_goal_completion: bool = Field(default=False)
    """Dynamic goal completion decision (optimization to skip extra LLM call when not needed)."""

    terminal_after_execute: bool = Field(default=False)
    """RFC-226: when True, the plan asserts its single step IS the goal completion.

    The Loop Graph routes from ``record_iteration`` directly to ``goal_completion``,
    skipping the iter=1 ``plan_assess`` status check. Set by the continuation-aware
    plan_assess for bootstrap actions; default False elsewhere.
    """

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
    IG-264: Minimal fields (status, progress) - 60% token reduction.
    IG-399: Descriptive progress levels instead of numeric.

    Attributes:
        status: Whether to finish, continue current plan, or replan.
        goal_progress: Descriptive progress level (none | low | medium | high | complete).
        assessment_reasoning: Brief justification for the status decision.
        require_goal_completion: Whether an extra goal completion LLM call is needed.
            When False, the last AIMessage from execution can be used as goal completion.
            Only relevant when status="done".
    """

    status: Literal["continue", "replan", "done"]
    goal_progress: Literal["none", "low", "medium", "high", "complete"] = "none"
    """Descriptive progress level - easier for LLMs to estimate accurately (IG-399)."""
    assessment_reasoning: str = ""
    """Brief status justification."""
    require_goal_completion: bool = Field(default=False)
    """Dynamic goal completion decision (optimization to skip extra LLM call when not needed)."""


class GoalComponentStatus(BaseModel):
    """One decomposed facet of the current GOAL and its evidence state (IG-557)."""

    component: str = Field(max_length=120)
    status: Literal["not_started", "partial", "satisfied", "blocked"]
    evidence: str = Field(default="", max_length=200)
    gap: str = Field(default="", max_length=200)


class PlanGapAnalysis(BaseModel):
    """Explicit evidence inventory + distance from GOAL (feeds plan-assess, IG-557)."""

    components: list[GoalComponentStatus] = Field(min_length=1, max_length=8)
    evidence_summary: str = Field(max_length=400)
    remaining_gaps: list[str] = Field(default_factory=list, max_length=6)
    distance_from_goal: Literal["far", "moderate", "near", "at_goal"]
    gap_reasoning: str = Field(max_length=300)


class ContinuationAssessment(BaseModel):
    """RFC-226: iter=0 routing decision for continuation queries.

    Emitted by ``LLMPlanner.assess_continuation`` on iter=0 of any agentic query
    where ``continue_loop_mode`` is True and the loop has at least one completed
    prior goal. Routes the new query to either a terminal bootstrap (one step
    using prior context) or the full ``plan_generate`` flow.

    Attributes:
        action: ``bootstrap`` for chat-like continuations answerable from prior
            context; ``plan_generate`` when new steps or new tools are required.
        reasoning: One first-person sentence (≤240 chars), e.g. "I'll …" or "I need … because …".
        goal_progress: Initial progress estimate; mirrors ``PlanResult.goal_progress``.
    """

    action: Literal["bootstrap", "plan_generate"] = Field(
        description=(
            "bootstrap: a single execute step using prior loop context can answer "
            "the query directly (no new tools needed). plan_generate: the query "
            "requires multiple steps, new tools, or cross-domain work — escalate "
            "to the full planner."
        ),
    )
    reasoning: str = Field(
        default="",
        max_length=240,
        description=(
            "One first-person sentence explaining the routing decision "
            '(e.g. "I will bootstrap from prior context.").'
        ),
    )
    goal_progress: Literal["none", "low", "medium", "high", "complete"] = "low"


class ToolCallHead(BaseModel):
    """One tool invocation captured from the most recent execute wave (RFC-227).

    Attributes:
        name: Tool name (e.g. ``run_command``, ``read_file``).
        head: First non-empty line of the tool message content, stripped and
            truncated at 120 chars. Empty string preserves the tool-name
            signal when the output is empty or unparseable.
    """

    name: str = Field(max_length=64)
    head: str = Field(default="", max_length=120)


class WaveStepProgress(BaseModel):
    """One executed step row in the most recent wave (RFC-227 plan-context digest)."""

    step_id: str = Field(default="", max_length=64)
    description: str = Field(default="", max_length=500)
    status: Literal["completed", "failed", "unknown"] = "unknown"
    outcome_preview: str = Field(default="", max_length=200)


class PriorProgressDigest(BaseModel):
    """Compact, truthful snapshot of the most recent execute wave (RFC-227).

    Refreshed by the executor at the end of every wave (parallel or sequential).
    Consumed by ``plan_assess`` and ``plan_generate`` via the
    ``PRIOR PROGRESS:`` section. Never used as a code-side override
    for the LLM's structured output — the deterministic ``derived_progress_hint``
    is shown verbatim so the LLM can disagree.

    Attributes:
        iteration: Iteration that produced the wave.
        wave_index: 0-based wave within that iteration.
        steps_completed: Number of successful steps in the wave.
        steps_failed: Number of failed steps in the wave.
        tool_calls: Up to 8 ``ToolCallHead`` rows in arrival order.
        evidence_excerpts: Up to 3 deduplicated AI-text excerpts, each ≤200 chars.
        step_summaries: Up to 8 per-step rows rendered like execute ``PRIOR STEPS``.
        derived_progress_hint: Pure-function classification over wave outputs.
    """

    iteration: int
    wave_index: int = 0
    steps_completed: int = 0
    steps_failed: int = 0
    tool_calls: list[ToolCallHead] = Field(default_factory=list, max_length=8)
    evidence_excerpts: list[str] = Field(default_factory=list, max_length=3)
    step_summaries: list[WaveStepProgress] = Field(default_factory=list, max_length=8)
    derived_progress_hint: Literal["none", "low", "medium", "high"] = "low"


DEFAULT_MAX_PLAN_STEPS_PER_WAVE = 10
"""Default maximum plan-generate steps per planning wave."""


class PlanGeneration(BaseModel):
    """Runtime plan-generate result (RFC-604).

    Built server-side from ``PlanGenerationWire`` LLM output (IG-568). Not sent
    directly as the structured-output schema to plan-generate models.

    Attributes:
        type: Decision type for the plan.
        steps: Steps for the plan. Required non-empty when ``type='execute_steps'``.
            May be empty when ``type='final'`` (same as ``AgentDecision``).
        execution_mode: Execution mode for ``steps``. When ``type`` is set but the model
            omits this field, it defaults to ``parallel``.
        reasoning: First-person plan rationale shown in the TUI cognition card
            (e.g. "I'll …", "Let me …").
        adaptive_granularity: Optional step granularity hint.
    """

    type: Literal["execute_steps", "final"] | None = None
    steps: list[PlanGenerateStep] = Field(default_factory=list)
    execution_mode: ExecutionMode | None = Field(
        default=None,
        description=(
            "Only 'parallel' (default when omitted) or 'dependency' if steps declare dependencies. "
            "Never 'sequential'."
        ),
    )
    reasoning: str = Field(
        default="",
        max_length=500,
        description=("First-person plan rationale for the cognition card (e.g. I'll …, Let me …)."),
    )
    adaptive_granularity: Literal["atomic", "semantic"] | None = None

    @model_validator(mode="before")
    @classmethod
    def _default_execution_mode(cls, data: Any) -> Any:
        """Default execution_mode when typed plan dict omits it."""
        if not isinstance(data, dict):
            return data
        if data.get("type") is None:
            return data
        if data.get("execution_mode") is None:
            return {**data, "execution_mode": "parallel"}
        return data

    @model_validator(mode="after")
    def _validate_generation_fields(self) -> PlanGeneration:
        """Ensure typed plan-generate output includes required step fields."""
        if self.type is None:
            raise ValueError("plan generation requires type")
        if self.type == "execute_steps" and not self.steps:
            raise ValueError("type 'execute_steps' requires non-empty steps")
        return self


def derive_plan_action(
    *,
    assessment_status: Literal["continue", "replan", "done"],
    has_remaining_steps: bool,
) -> Literal["keep", "new"]:
    """Derive runtime plan reuse vs replace from assess status and in-flight plan state.

    Args:
        assessment_status: Status from the assess phase.
        has_remaining_steps: Whether ``current_decision`` still has pending steps.

    Returns:
        ``keep`` when assess says continue and pending steps remain; otherwise ``new``.
    """
    if assessment_status == "continue" and has_remaining_steps:
        return "keep"
    return "new"


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
        tool_call_count: Main-graph tool calls during execution (excludes subgraph).
        subgraph_tool_call_count: Namespaced subagent tool calls during execution.
        subagent_task_completions: Completed ``task`` tool results at graph root (IG-130).
        hit_subagent_cap: True when streaming stopped early due to subagent task cap (IG-130).
        hit_tool_budget: True when streaming stopped early due to per-step tool call cap.
    """

    step_id: str
    success: bool
    outcome: dict = Field(default_factory=dict)  # RFC-211
    error: str | None = None
    error_type: Literal["execution", "tool", "timeout", "policy", "unknown", "fatal"] | None = None
    duration_ms: int
    thread_id: str
    tool_call_count: int = 0
    subgraph_tool_call_count: int = 0
    subagent_task_completions: int = 0
    hit_subagent_cap: bool = False
    hit_tool_budget: bool = False

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


# Memory bounds for unbounded lists (IG-475)
MAX_STEP_RESULTS_PER_GOAL = 50  # Cap historical step results
MAX_LOOP_MESSAGES_PER_GOAL = 200  # Cap message ledger
MAX_ACTION_HISTORY_PER_GOAL = 20  # Cap action descriptions
MAX_EVIDENCE_LEDGER_PER_GOAL = 100  # Cap evidence entries

# RFC-624 Phase 4: StepResult mapping helpers
_VALID_ERROR_TYPES = {"execution", "tool", "timeout", "policy", "unknown", "fatal"}


def _clamp_error_type(raw: str | None) -> str | None:
    """Clamp error_type to StepResult's Literal union; unknown values → 'unknown'."""
    if raw is None:
        return None
    return raw if raw in _VALID_ERROR_TYPES else "unknown"


def _step_node_to_result(node: Any) -> StepResult:
    """Map CE StepNode + StepExecution to LoopState StepResult."""
    ex = node.execution
    return StepResult(
        step_id=node.id,
        success=node.status == "completed",
        outcome=ex.outcome or {},
        error=ex.error,
        error_type=_clamp_error_type(ex.error_type),
        duration_ms=ex.duration_ms,
        thread_id=ex.thread_id or "",
        tool_call_count=ex.tool_call_count,
        subagent_task_completions=ex.subagent_task_completions,
        hit_subagent_cap=ex.hit_subagent_cap,
        hit_tool_budget=ex.hit_tool_budget,
    )


class LoopState(BaseModel):
    """State for agentic loop (RFC-201, RFC-214).

    IG-475: Bounded lists prevent memory leaks from unbounded accumulation during
    long-running queries with many iterations.

    Attributes:
        goal: Goal description (after any ``/skill:`` expansion for orchestration).
        goal_user_submission: Original user line when ``goal`` was expanded from ``/skill:``;
            used for Langfuse trace input so dashboards stay aligned with submitted text.
        skill_context: Skill reference only (SKILL.md body) when ``goal`` was expanded from
            ``/skill:``; used in execute-step ``<SKILL_CONTEXT>`` (not the full composed goal).
        thread_id: Thread context
        workspace: Thread-specific workspace path (RFC-103)
        iteration: Current iteration number
        max_iterations: Maximum iterations allowed
        current_decision: Current AgentDecision being executed
        plan_id: Active plan scope (3 uppercase letters); new plan allocates, keep reuses (IG-303).
        completed_step_ids: Set of completed step IDs (CE-backed property when bound)
        previous_plan: Previous Plan phase result
        step_results: All step results from execution (CE-backed property when bound)
        evidence_summary: Accumulated evidence summary
        started_at: Loop start timestamp
        total_duration_ms: Total loop duration
        working_memory: Loop working-memory instance (RFC-203) when enabled.
        loop_messages: RFC-214: Unified message ledger (CE-backed property when bound).
        last_wave_answer_from_delegate_final: True when the latest execute wave answer came from ``task`` tool returns
            (``task_tool_aggregate`` provenance), not root-graph assistant stream (IG-355).
        last_execute_wave_parallel_multi_step: True when the last wave ran multiple parallel steps (IG-199).
        continue_loop: RFC-225 flag — True when this loop has prior goals (carrier for executor wiring).
        prior_progress: RFC-227 per-wave digest produced by executor, consumed by plan-assess/plan-generate.
    """

    goal: str
    goal_user_submission: str | None = Field(
        default=None,
        description="User-submitted line before /skill: expansion (Langfuse / UX).",
    )
    skill_context: str | None = Field(
        default=None,
        description="Skill reference text for execute-step SKILL_CONTEXT when goal expanded from /skill:.",
    )
    thread_id: str
    workspace: str | None = None  # Thread-specific workspace (RFC-103)
    iteration: int = 0
    max_iterations: int = DEFAULT_STRANGE_LOOP_MAX_ITERATIONS

    current_decision: AgentDecision | None = None
    plan_id: str | None = None
    previous_plan: PlanResult | None = None
    evidence_summary: str = ""
    working_memory: Any | None = None

    # CE-backed property caches (RFC-624 Phase 4). When CE is not bound,
    # these caches serve as the authoritative store. When CE is bound,
    # the @property accessors query CE and these caches are unused.
    _loop_messages_cache: list[LoopHumanMessage | LoopAIMessage] = PrivateAttr(default_factory=list)
    _step_results_cache: list[StepResult] = PrivateAttr(default_factory=list)
    _completed_step_ids_cache: set[str] = PrivateAttr(default_factory=set)

    evidence_ledger: list[EvidenceEntry] = Field(
        default_factory=list,
        description="Append-only evidence ids for plan validation.",
    )

    # RFC-624 Phase 4: CE binding. When set, @property accessors query CE
    # for loop_messages, step_results, and completed_step_ids.
    _ce: Any | None = PrivateAttr(default=None)
    _ce_goal_id: str | None = PrivateAttr(default=None)
    # Temporary storage for property kwargs captured by the before-validator.
    # Not thread-safe but LoopState is not shared across threads.
    _pending_kwargs: dict[str, Any] = PrivateAttr(default_factory=dict)

    @model_validator(mode="before")
    @classmethod
    def _capture_property_kwargs(cls, data: Any) -> Any:
        """Route loop_messages/step_results/completed_step_ids kwargs to caches.

        These fields are @property accessors (not Pydantic fields), but callers
        may still pass them as constructor kwargs. This validator extracts them
        so they can be assigned after Pydantic construction.
        """
        if isinstance(data, dict):
            data = dict(data)  # avoid mutating the original
            captured = {
                k: data.pop(k)
                for k in ("loop_messages", "step_results", "completed_step_ids")
                if k in data
            }
            # Stash on the class for post-init assignment; safe because
            # LoopState construction is single-threaded per instance.
            cls._pending_kwargs_store = captured  # type: ignore[attr-defined]
        return data

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        # Apply any captured property kwargs to the private caches
        pending = getattr(self.__class__, "_pending_kwargs_store", {})
        if pending:
            if "loop_messages" in pending:
                self._loop_messages_cache = pending["loop_messages"]
            if "step_results" in pending:
                self._step_results_cache = pending["step_results"]
            if "completed_step_ids" in pending:
                self._completed_step_ids_cache = pending["completed_step_ids"]
            self.__class__._pending_kwargs_store = {}

    started_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    total_duration_ms: int = 0

    # Last Act wave metrics for Plan prompts (IG-130, IG-132)
    last_wave_tool_call_count: int = 0
    last_wave_subagent_task_count: int = 0
    last_wave_hit_subagent_cap: bool = False
    last_wave_hit_tool_budget: bool = False
    last_wave_output_length: int = 0
    last_wave_error_count: int = 0
    total_tokens_used: int = 0
    context_percentage_consumed: float = 0.0

    # Action history for progressive specificity tracking (RFC-603)
    action_history: list[str] = Field(
        default_factory=list,
        description="Chronological action descriptions for progression tracking",
    )

    # Last Execute wave provenance for adaptive final response (IG-199, IG-355)
    last_wave_answer_from_delegate_final: bool = False
    last_execute_wave_parallel_multi_step: bool = False
    continue_loop: bool = False  # RFC-225: True when loop has prior goals

    # RFC-227: per-wave digest produced by executor, consumed by plan-assess/plan-generate.
    prior_progress: PriorProgressDigest | None = Field(
        default=None,
        description="Most-recent execute wave snapshot for plan-phase grounding.",
    )

    # RFC-105: Progressive skill loading durability snapshot
    sent_skill_names: set[str] = Field(default_factory=set)
    activated_skill_names: set[str] = Field(default_factory=set)
    invoked_skill_names: set[str] = Field(default_factory=set)
    invoked_skill_bodies: dict[str, str] = Field(default_factory=dict)

    # Progressive builtin-tool loading durability snapshot
    sent_tool_names: set[str] = Field(default_factory=set)
    promoted_tool_names: set[str] = Field(default_factory=set)

    # RFC-412: MCP progressive disclosure durability snapshot
    sent_mcp_tool_names: set[str] = Field(default_factory=set)
    invoked_mcp_tools: dict[str, dict] = Field(default_factory=dict)
    disabled_mcp_servers: set[str] = Field(default_factory=set)
    cached_mcp_resources: dict[str, str] = Field(default_factory=dict)

    # Slash invocation signal — consumed once by executor then cleared
    slash_invoked_skill_name: str | None = Field(
        default=None,
        description="Skill name from /skill: expansion; seeded into skill_activation by executor.",
    )
    slash_invoked_skill_body: str | None = Field(
        default=None,
        description="Skill body from /skill: expansion; seeded into skill_activation by executor.",
    )
    intent: Any | None = None  # IG-268: Intent classification for response length intelligence
    routing_classification: Any | None = Field(
        default=None,
        description="RoutingClassification for Plan + Execute.",
    )

    # Thread tracking for step isolation (IG-477: message injection, no checkpoint fork)
    step_thread_ids: dict[str, str] = Field(
        default_factory=dict,
        description="Maps step_id → thread_id used for execution.",
    )

    def bind_ce(self, ce: Any, goal_id: str) -> None:
        """Bind this LoopState to a ContextEngine instance (RFC-624 Phase 4).

        After binding, @property accessors for loop_messages, step_results,
        and completed_step_ids query CE instead of the local cache.

        Args:
            ce: ContextEngine instance.
            goal_id: Active goal ID in the CE DAG.
        """
        self._ce = ce
        self._ce_goal_id = goal_id
        # Clear caches — CE is now authoritative
        self._loop_messages_cache.clear()
        self._step_results_cache.clear()
        self._completed_step_ids_cache.clear()

    @property
    def loop_messages(self) -> list[LoopHumanMessage | LoopAIMessage]:
        """Ordered adjacent Human-AI message pairs for all orchestration turns.

        When CE is bound, queries the CE ledger (fresh data each call).
        When CE is not bound, returns the local cache.
        """
        if self._ce is None:
            return self._loop_messages_cache
        return self._build_loop_messages_from_ce()

    @loop_messages.setter
    def loop_messages(self, value: list[LoopHumanMessage | LoopAIMessage]) -> None:
        """Allow legacy assignment (e.g., constructor). Writes to cache only."""
        self._loop_messages_cache = value

    @property
    def step_results(self) -> list[StepResult]:
        """Step execution results. When CE is bound, derived from CE StepDAG."""
        if self._ce is None:
            return self._step_results_cache
        return self._build_step_results_from_ce()

    @step_results.setter
    def step_results(self, value: list[StepResult]) -> None:
        """Allow legacy assignment. Writes to cache only."""
        self._step_results_cache = value

    @property
    def completed_step_ids(self) -> set[str]:
        """Set of completed step IDs. When CE is bound, derived from CE StepDAG."""
        if self._ce is None:
            return self._completed_step_ids_cache
        try:
            goal = self._ce.get_goal_sync(self._ce_goal_id)
            if goal is None:
                return set()
            return {sid for sid, n in goal.steps.nodes.items() if n.status == "completed"}
        except Exception:
            logger.warning("completed_step_ids property: CE query failed", exc_info=True)
            return self._completed_step_ids_cache

    @completed_step_ids.setter
    def completed_step_ids(self, value: set[str]) -> None:
        """Allow legacy assignment. Writes to cache only."""
        self._completed_step_ids_cache = value

    def _build_loop_messages_from_ce(self) -> list[LoopHumanMessage | LoopAIMessage]:
        """Convert CE ledger entries to Loop message types."""
        from langchain_core.messages import AIMessage, HumanMessage

        result: list[LoopHumanMessage | LoopAIMessage] = []
        try:
            for msg, phase in self._ce.ledger.entries():
                if isinstance(msg, (LoopHumanMessage, LoopAIMessage)):
                    result.append(msg)
                elif isinstance(msg, HumanMessage):
                    result.append(
                        LoopHumanMessage(
                            content=msg.content,
                            phase=phase,
                            **{
                                k: v
                                for k, v in msg.model_dump().items()
                                if k
                                in (
                                    "thread_id",
                                    "iteration",
                                    "goal_summary",
                                    "workspace",
                                    "wave_id",
                                    "core_agent_message_id",
                                )
                                and v is not None
                            },
                        )
                    )
                elif isinstance(msg, AIMessage):
                    result.append(
                        LoopAIMessage(
                            content=msg.content,
                            phase=phase,
                            **{
                                k: v
                                for k, v in msg.model_dump().items()
                                if k
                                in ("thread_id", "iteration", "wave_id", "core_agent_message_id")
                                and v is not None
                            },
                        )
                    )
        except Exception:
            logger.warning("loop_messages property: CE query failed", exc_info=True)
            return self._loop_messages_cache
        return result

    def _build_step_results_from_ce(self) -> list[StepResult]:
        """Map CE StepNode + StepExecution to StepResult."""
        try:
            goal = self._ce.get_goal_sync(self._ce_goal_id)
            if goal is None:
                return []
            results = []
            for node in goal.steps.nodes.values():
                if node.execution is not None:
                    results.append(_step_node_to_result(node))
            return results
        except Exception:
            logger.warning("step_results property: CE query failed", exc_info=True)
            return self._step_results_cache

    def add_step_result(self, result: StepResult) -> None:
        """Add step result and update completed set with bounded accumulation (IG-475).

        When CE is bound, this is a no-op — CE writes (``complete_step``,
        ``fail_step``) are the sole mutation path. When CE is not bound,
        writes to the local cache.

        Args:
            result: Step execution result
        """
        if self._ce is not None:
            return
        self._step_results_cache.append(result)
        if result.success:
            self._completed_step_ids_cache.add(result.step_id)
        # IG-475: Trim old results to prevent unbounded memory growth
        if len(self._step_results_cache) > MAX_STEP_RESULTS_PER_GOAL:
            excess = len(self._step_results_cache) - MAX_STEP_RESULTS_PER_GOAL
            self._step_results_cache = self._step_results_cache[excess:]

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
        return set(self.completed_step_ids) | historical

    def add_action_to_history(self, action: str) -> None:
        """Add action description to history with bounded accumulation (IG-475).

        Args:
            action: Action description text
        """
        if action and action.strip():
            self.action_history.append(action.strip())
            # IG-475: Trim old actions to prevent unbounded growth
            if len(self.action_history) > MAX_ACTION_HISTORY_PER_GOAL:
                self.action_history = self.action_history[-MAX_ACTION_HISTORY_PER_GOAL:]

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

    def trim_loop_messages(self) -> None:
        """Trim loop_messages to bounded size (IG-475).

        When CE is bound, trimming is unnecessary — CE ledger is authoritative
        and the _build_loop_messages_from_ce helper applies its own bound.
        When CE is not bound, trims the local cache.
        """
        if self._ce is not None:
            return
        if len(self._loop_messages_cache) > MAX_LOOP_MESSAGES_PER_GOAL:
            excess = len(self._loop_messages_cache) - MAX_LOOP_MESSAGES_PER_GOAL
            self._loop_messages_cache = self._loop_messages_cache[excess:]
            logger.debug(
                "Trimmed loop_messages from %d to %d (thread=%s)",
                len(self._loop_messages_cache) + excess,
                len(self._loop_messages_cache),
                self.thread_id[:16],
            )

    def trim_evidence_ledger(self) -> None:
        """Trim evidence_ledger to bounded size (IG-475).

        Keeps the most recent evidence entries for plan validation.
        """
        if len(self.evidence_ledger) > MAX_EVIDENCE_LEDGER_PER_GOAL:
            excess = len(self.evidence_ledger) - MAX_EVIDENCE_LEDGER_PER_GOAL
            self.evidence_ledger = self.evidence_ledger[excess:]
            logger.debug(
                "Trimmed evidence_ledger from %d to %d",
                len(self.evidence_ledger) + excess,
                len(self.evidence_ledger),
            )

    def clear_goal_state(self) -> None:
        """Clear execution state after goal completion (IG-475).

        Called by goal_completion node to reset state for the next query.
        Prevents task leakage where pending state from one query persists
        into the next.
        """
        # Clear decision and step state
        self.current_decision = None
        self.plan_id = None
        # RFC-624 Phase 4 Stage 2: Clear cache fields directly (not property returns).
        # When CE is bound, property reads from DAG so cache is irrelevant.
        # When CE is not bound (tests), cache needs to be cleared.
        self._completed_step_ids_cache.clear()
        self._step_results_cache.clear()

        # Clear evidence and working memory
        self.evidence_ledger.clear()
        self.evidence_summary = ""
        if self.working_memory is not None:
            try:
                self.working_memory.clear()
            except Exception:
                logger.debug("Failed to clear working_memory (thread=%s)", self.thread_id[:16])

        # Clear wave metrics
        self.last_wave_tool_call_count = 0
        self.last_wave_subagent_task_count = 0
        self.last_wave_hit_subagent_cap = False
        self.last_wave_hit_tool_budget = False
        self.last_wave_output_length = 0
        self.last_wave_error_count = 0

        # Clear prior progress digest
        self.prior_progress = None

        # Trim but don't fully clear loop_messages - keep recent context
        self.trim_loop_messages()

        # IG-477补充：清理未绑定的dict，防止跨goal累积
        self.invoked_skill_bodies.clear()
        self.cached_mcp_resources.clear()

        logger.info(
            "Cleared goal state for thread=%s (iteration=%d)",
            self.thread_id[:16],
            self.iteration,
        )
