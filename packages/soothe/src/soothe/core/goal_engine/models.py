"""Goal models for autonomous iteration (RFC-0007, RFC-204, RFC-200, RFC-217)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

from soothe.protocols.planner import GoalReport

# RFC-204: Extended lifecycle states (7 total)
GoalStatus = Literal[
    "pending", "active", "validated", "completed", "failed", "suspended", "blocked"
]

# Terminal states that count as "resolved"
TERMINAL_STATES: frozenset[str] = frozenset({"completed", "failed"})


class Goal(BaseModel):
    """A single autonomous goal.

    Args:
        id: Unique 8-char hex identifier.
        description: Human-readable goal text.
        status: Current lifecycle status (7 states per RFC-204).
        priority: Scheduling priority (0-100, higher = first).
        parent_id: Optional parent goal for hierarchical decomposition.
        depends_on: IDs of goals that must complete before this one (hard DAG edges).
        informs: IDs of goals whose findings may enrich this goal (soft dependency).
        conflicts_with: IDs of goals that must not execute concurrently (mutual exclusion).
        plan_count: Number of plans created for this goal (for P_N ID generation).
        retry_count: Number of retries attempted so far.
        max_retries: Maximum retries before permanent failure.
        send_back_count: Number of consensus send-backs used (RFC-204).
        max_send_backs: Maximum send-back rounds before suspension (RFC-204).
        error: Error message if goal failed (IG-155 for file tracking).
        report: GoalReport from execution (set on completion).
        source_file: Path to GOAL.md file that defined this goal (None if auto-created).
        created_at: Creation timestamp.
        updated_at: Last update timestamp.
        assigned_loop_id: Loop assigned to this goal (RFC-222).
        lock_status: File lock status for this goal (RFC-222).
        locked_files: Files currently locked by this goal (RFC-222).
        lock_acquired_at: Timestamp when lock acquired (RFC-222).
        workspace: Absolute filesystem workspace for execution (RFC-222).
            When unset, the worker falls back to a per-loop persisted sandbox.
    """

    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:8])
    description: str
    status: GoalStatus = "pending"
    priority: int = 50
    parent_id: str | None = None
    depends_on: list[str] = Field(default_factory=list)
    # RFC-204: Soft relationships and mutual exclusion
    informs: list[str] = Field(default_factory=list)
    conflicts_with: list[str] = Field(default_factory=list)
    plan_count: int = 0
    retry_count: int = 0
    max_retries: int = 2
    # RFC-204: Consensus loop tracking
    send_back_count: int = 0
    max_send_backs: int = 3
    error: str | None = None  # IG-155: Error message for file tracking
    report: GoalReport | None = None
    # RFC-204, IG-155: Source file for status tracking
    source_file: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    # RFC-222: Autopilot-specific fields for loop assignment and file locking
    assigned_loop_id: str | None = None
    lock_status: Literal["none", "acquired", "released"] = "none"
    locked_files: list[str] = Field(default_factory=list)
    lock_acquired_at: datetime | None = None
    # RFC-222 H4: incremented each time crash recovery resets this goal from
    # ``active`` back to ``pending`` on daemon start.
    attempts_after_crash: int = 0
    # RFC-222: client workspace for autopilot dispatch (optional).
    workspace: str | None = None


# RFC-200 §14-22: Canonical evidence bundle for Layer 2 → Layer 3 integration
class EvidenceBundle(BaseModel):
    """Canonical evidence payload exchanged across Layer 2 and Layer 3.

    RFC-200 §14-22: This is the authoritative schema for evidence exchange.
    Layer 2 AgentLoop MUST construct this structure from execution context.
    Layer 3 GoalEngine MUST receive this in fail_goal() signature.

    Args:
        structured: Machine-readable execution metrics/state for deterministic processing.
        narrative: Natural language synthesis for LLM reasoning and operator visibility.
        source: Evidence producer stage (layer2_execute, layer2_plan, layer3_reflect).
        timestamp: Evidence emission time.
    """

    structured: dict[str, Any] = Field(
        description="Machine-readable execution metrics/state for deterministic processing"
    )
    narrative: str = Field(
        description="Natural language synthesis for LLM reasoning and operator visibility"
    )
    source: Literal["layer2_execute", "layer2_plan", "layer3_reflect"] = Field(
        description="Evidence producer stage"
    )
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(UTC), description="Evidence emission time"
    )


# RFC-200 §205-541: Backoff decision for goal DAG restructuring
class BackoffDecision(BaseModel):
    """LLM-driven backoff decision for goal DAG restructuring.

    RFC-200 §205-541: GoalBackoffReasoner output structure.
    Determines WHERE to backoff in goal DAG and what directives to apply.

    Args:
        backoff_to_goal_id: Target goal to backoff to (where to resume in DAG).
        reason: Natural language reasoning for backoff decision.
        new_directives: Additional directives to apply after backoff.
        evidence_summary: Summary of why current goal path failed.
    """

    backoff_to_goal_id: str = Field(
        description="Target goal to backoff to (where to resume in DAG)"
    )
    reason: str = Field(description="Natural language reasoning for backoff decision")
    new_directives: list[dict[str, Any]] = Field(
        default_factory=list, description="Additional directives to apply after backoff"
    )
    evidence_summary: str = Field(description="Summary of why current goal path failed")


# RFC-200 §14-22: DAG execution status for backoff and reflection
class GoalSubDAGStatus(BaseModel):
    """Canonical DAG execution status for backoff and reflection.

    RFC-200 §14-22: Tracks goal execution states and backoff boundaries.
    Used by GoalEngine for DAG state management.

    Args:
        execution_states: Per-goal execution state.
        backoff_points: Goal IDs selected as backoff boundaries.
        evidence_annotations: Per-goal evidence mapping.
    """

    execution_states: dict[
        str, Literal["pending", "running", "success", "failed", "backoff_pending"]
    ] = Field(description="Per-goal execution state")
    backoff_points: list[str] = Field(
        default_factory=list, description="Goal IDs selected as backoff boundaries"
    )
    evidence_annotations: dict[str, EvidenceBundle] = Field(
        default_factory=dict, description="Per-goal evidence mapping"
    )


# RFC-217 §95-172: Context construction options for thread selection
class ContextConstructionOptions(BaseModel):
    """Options for goal context construction.

    RFC-217 §95-172: Thread selection and similarity filtering configuration.
    Used by ThreadRelationshipModule and GoalContextManager.

    Args:
        include_same_goal_threads: Include multiple threads for same goal_id.
        include_similar_goals: Include threads with semantically similar goals.
        thread_selection_strategy: Strategy for selecting relevant threads.
        similarity_threshold: Embedding similarity threshold for goal matching.
    """

    include_same_goal_threads: bool = Field(
        default=True, description="Include multiple threads for same goal_id"
    )
    include_similar_goals: bool = Field(
        default=True, description="Include threads with semantically similar goals"
    )
    thread_selection_strategy: Literal["latest", "all", "best_performing"] = Field(
        default="latest", description="Strategy for selecting relevant threads"
    )
    similarity_threshold: float = Field(
        default=0.7, description="Embedding similarity threshold for goal matching", ge=0.0, le=1.0
    )


# ---------------------------------------------------------------------------
# RFC-222 (revised): GoalDispatchContext* — bounded summary types that flow
# between the daemon's AutopilotService and subprocess AgentLoop workers.
# Distinct from RFC-217 GoalContext (thread ecosystem) and RFC-200 GoalContext
# (DAG snapshot for backoff) — see RFC-222 §"GoalDispatchContext".
# ---------------------------------------------------------------------------


_BUNDLE_DEFAULT_MAX_FINDINGS = 20
_BUNDLE_DEFAULT_MAX_FILES = 50
_BUNDLE_DEFAULT_MAX_PLAN_STEPS = 30
_BUNDLE_DEFAULT_MAX_FINDING_CHARS = 2000


class PriorStepSummary(BaseModel):
    """One step from a parent goal's plan ledger, summarized for hydration."""

    id: str
    description: str
    status: Literal["completed", "failed", "skipped"]
    duration_ms: int | None = None
    goal_id_origin: str = Field(description="Goal that originally produced this step")


class FileTouchSummary(BaseModel):
    """One file touched by a parent goal — path + hash, never raw contents."""

    content_hash: str = Field(description="Hash of the file contents at last touch")
    last_op: Literal["read", "write", "edit", "delete"]
    goal_id_origin: str
    last_touched_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class ParentFinding(BaseModel):
    """LLM-synthesized finding from a parent goal, with provenance."""

    goal_id_origin: str
    summary: str = Field(max_length=_BUNDLE_DEFAULT_MAX_FINDING_CHARS)
    relevance_score: float = Field(ge=0.0, le=1.0, default=0.5)


class Finding(BaseModel):
    """A finding produced by the currently-executing goal (output side)."""

    summary: str = Field(max_length=_BUNDLE_DEFAULT_MAX_FINDING_CHARS)
    relevance_score: float = Field(ge=0.0, le=1.0, default=0.5)


class StepSummary(BaseModel):
    """One step from the currently-executing goal's plan (output side)."""

    id: str
    action: str
    outcome: Literal["completed", "failed", "skipped"]
    duration_ms: int | None = None


class ToolCallStats(BaseModel):
    """Aggregate tool-call counts. Useful for both input and output sides."""

    counts_by_name: dict[str, int] = Field(default_factory=dict)
    failures_by_name: dict[str, int] = Field(default_factory=dict)

    def total_calls(self) -> int:
        return sum(self.counts_by_name.values())

    def total_failures(self) -> int:
        return sum(self.failures_by_name.values())


class GoalDispatchContextBundle(BaseModel):
    """Immutable hydration input for AgentLoop (RFC-222 revised).

    Built by the daemon's ContextProjector from a goal's parents'
    GoalDispatchContextContribution entries. Bounded — summaries only,
    not raw transcripts. AgentLoop never sees the DAG; it sees this
    pre-merged bundle.
    """

    prior_plan_steps: list[PriorStepSummary] = Field(default_factory=list)
    files_touched: dict[str, FileTouchSummary] = Field(default_factory=dict)
    findings: list[ParentFinding] = Field(default_factory=list)
    tool_call_summary: ToolCallStats = Field(default_factory=ToolCallStats)
    cached_system_prompt_hash: str | None = Field(
        default=None,
        description="Stable hash of the provider-cached system prompt prefix, when available",
    )

    @model_validator(mode="after")
    def _enforce_bounds(self) -> GoalDispatchContextBundle:
        """Hard caps — bundle stays small enough to ship over IPC cheaply."""
        if len(self.findings) > _BUNDLE_DEFAULT_MAX_FINDINGS:
            msg = (
                f"GoalDispatchContextBundle.findings ({len(self.findings)}) exceeds "
                f"max {_BUNDLE_DEFAULT_MAX_FINDINGS}"
            )
            raise ValueError(msg)
        if len(self.files_touched) > _BUNDLE_DEFAULT_MAX_FILES:
            msg = (
                f"GoalDispatchContextBundle.files_touched ({len(self.files_touched)}) exceeds "
                f"max {_BUNDLE_DEFAULT_MAX_FILES}"
            )
            raise ValueError(msg)
        if len(self.prior_plan_steps) > _BUNDLE_DEFAULT_MAX_PLAN_STEPS:
            msg = (
                f"GoalDispatchContextBundle.prior_plan_steps ({len(self.prior_plan_steps)}) "
                f"exceeds max {_BUNDLE_DEFAULT_MAX_PLAN_STEPS}"
            )
            raise ValueError(msg)
        return self


class GoalDispatchContextContribution(BaseModel):
    """What one goal's execution adds back to the DAG's context pool.

    Emitted by the worker exactly once, just before the terminal `done`
    chunk, inside the GoalCompletionChunk. Daemon stores it in
    GoalDispatchContextStore keyed by goal_id; ContextProjector reads
    parents' contributions to build a successor's bundle.
    """

    plan_steps_executed: list[StepSummary] = Field(default_factory=list)
    files_touched: dict[str, FileTouchSummary] = Field(default_factory=dict)
    findings: list[Finding] = Field(default_factory=list)
    tool_call_stats: ToolCallStats = Field(default_factory=ToolCallStats)

    @model_validator(mode="after")
    def _enforce_bounds(self) -> GoalDispatchContextContribution:
        if len(self.findings) > _BUNDLE_DEFAULT_MAX_FINDINGS:
            msg = (
                f"GoalDispatchContextContribution.findings ({len(self.findings)}) exceeds "
                f"max {_BUNDLE_DEFAULT_MAX_FINDINGS}"
            )
            raise ValueError(msg)
        if len(self.files_touched) > _BUNDLE_DEFAULT_MAX_FILES:
            msg = (
                f"GoalDispatchContextContribution.files_touched ({len(self.files_touched)}) "
                f"exceeds max {_BUNDLE_DEFAULT_MAX_FILES}"
            )
            raise ValueError(msg)
        if len(self.plan_steps_executed) > _BUNDLE_DEFAULT_MAX_PLAN_STEPS:
            msg = (
                f"GoalDispatchContextContribution.plan_steps_executed "
                f"({len(self.plan_steps_executed)}) exceeds max {_BUNDLE_DEFAULT_MAX_PLAN_STEPS}"
            )
            raise ValueError(msg)
        return self
