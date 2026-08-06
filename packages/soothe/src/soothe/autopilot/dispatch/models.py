"""Goal models for autonomous iteration (RFC-204, RFC-200, RFC-217, RFC-222, RFC-625).

All goal state is managed via GoalNode in soothe.context.models. This module
retains models used for:
- Evidence/Backoff: LLM-driven backoff reasoning
- GoalDispatchContext*: IPC between daemon and workers
- Status constants: Shared lifecycle state definitions
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

# RFC-204: Extended lifecycle states; RFC-622: + awaiting_clarification
GoalStatus = Literal[
    "pending",
    "active",
    "validated",
    "completed",
    "failed",
    "cancelled",
    "suspended",
    "blocked",
    "awaiting_clarification",
]

# Terminal states that count as "resolved"
TERMINAL_STATES: frozenset[str] = frozenset({"completed", "failed", "cancelled"})

# RFC-622: states that block the scheduler from picking the goal up
BLOCKED_STATES: frozenset[str] = frozenset({"awaiting_clarification", "suspended"})


# Canonical evidence bundle for StrangeLoop → AutopilotMonitor integration
class EvidenceBundle(BaseModel):
    """Canonical evidence payload exchanged across StrangeLoop and Autopilot.

    This is the authoritative schema for evidence exchange.
    StrangeLoop MUST construct this structure from execution context.
    ContextEngine (via AutopilotMonitor) MUST receive this in fail_goal() signature.

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


# ---------------------------------------------------------------------------
# RFC-222 (revised): GoalDispatchContext* — bounded summary types that flow
# between the daemon's AutopilotService and subprocess StrangeLoop workers.
# Distinct from RFC-217 GoalContext (thread ecosystem) and RFC-200 GoalContext
# (DAG snapshot for backoff) — see RFC-222 §"GoalDispatchContext".
# ---------------------------------------------------------------------------


_BUNDLE_DEFAULT_MAX_FINDINGS = 20
_BUNDLE_DEFAULT_MAX_EFFECTS = 50
_BUNDLE_DEFAULT_MAX_PLAN_STEPS = 30
_BUNDLE_DEFAULT_MAX_FINDING_CHARS = 2000

GoalEffectKind = Literal["produce", "mutate", "observe", "communicate", "decide"]


class PriorStepSummary(BaseModel):
    """One step from a parent goal's plan ledger, summarized for hydration."""

    id: str
    description: str
    status: Literal["completed", "failed", "skipped"]
    duration_ms: int | None = None
    goal_id_origin: str = Field(description="Goal that originally produced this step")


class GoalEffect(BaseModel):
    """One claimed side-effect of a completed goal — domain-agnostic (IG-712).

    Opaque to the host: ``ref`` may be a path, URL, ticket id, channel, or
    ``answer`` for narrative-only work. Never inferred from prose or the
    filesystem; StrangeLoop emits these via structured assess output.
    """

    kind: GoalEffectKind
    ref: str = Field(max_length=512, description="Opaque handle for the affected subject")
    statement: str = Field(max_length=500, description="One-line claim about what happened")
    digest: str | None = Field(
        default=None,
        max_length=128,
        description="Optional version/hash when the domain has one",
    )
    confidence: float = Field(default=0.8, ge=0.0, le=1.0)
    goal_id_origin: str | None = Field(
        default=None,
        description="Parent goal id when projected into a successor bundle",
    )


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
    """Immutable hydration input for StrangeLoop (RFC-222 revised).

    Built by the daemon's ContextProjector from a goal's parents'
    GoalDispatchContextContribution entries. Bounded — summaries only,
    not raw transcripts. StrangeLoop never sees the DAG; it sees this
    pre-merged bundle.
    """

    prior_plan_steps: list[PriorStepSummary] = Field(default_factory=list)
    prior_effects: list[GoalEffect] = Field(default_factory=list)
    findings: list[ParentFinding] = Field(default_factory=list)
    tool_call_summary: ToolCallStats = Field(default_factory=ToolCallStats)
    operator_guidance: list[str] = Field(
        default_factory=list,
        description="Operator guidance texts absorbed via RFC-228 job_guidance",
    )
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
        if len(self.prior_effects) > _BUNDLE_DEFAULT_MAX_EFFECTS:
            msg = (
                f"GoalDispatchContextBundle.prior_effects ({len(self.prior_effects)}) exceeds "
                f"max {_BUNDLE_DEFAULT_MAX_EFFECTS}"
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

    model_config = ConfigDict(extra="ignore")

    plan_steps_executed: list[StepSummary] = Field(default_factory=list)
    effects: list[GoalEffect] = Field(default_factory=list)
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
        if len(self.effects) > _BUNDLE_DEFAULT_MAX_EFFECTS:
            msg = (
                f"GoalDispatchContextContribution.effects ({len(self.effects)}) "
                f"exceeds max {_BUNDLE_DEFAULT_MAX_EFFECTS}"
            )
            raise ValueError(msg)
        if len(self.plan_steps_executed) > _BUNDLE_DEFAULT_MAX_PLAN_STEPS:
            msg = (
                f"GoalDispatchContextContribution.plan_steps_executed "
                f"({len(self.plan_steps_executed)}) exceeds max {_BUNDLE_DEFAULT_MAX_PLAN_STEPS}"
            )
            raise ValueError(msg)
        return self
