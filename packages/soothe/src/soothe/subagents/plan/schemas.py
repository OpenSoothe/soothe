"""Pydantic schemas for the plan subagent (RFC-618)."""

from __future__ import annotations

from pydantic import BaseModel, Field


class PlanSubagentConfig(BaseModel):
    """YAML configuration under ``subagents.plan.config``."""

    enable_explore: bool = Field(
        default=True,
        description="When true, collection rounds may invoke the explore runnable.",
    )
    max_explore_passes: int = Field(
        default=24,
        ge=0,
        le=128,
        description="Hard cap on total explore sub-invocations across all collection rounds.",
    )
    max_collection_rounds: int = Field(
        default=6,
        ge=1,
        le=32,
        description="Maximum agentic collection iterations (LLM decides explore batches each round).",
    )
    max_explore_tasks_per_round: int = Field(
        default=8,
        ge=0,
        le=32,
        description="Upper bound on explore directives executed in a single collection round.",
    )
    max_plan_rounds: int = Field(
        default=5,
        ge=1,
        le=24,
        description="Maximum agentic plan-design iterations before the draft is emitted.",
    )


class CollectorDecision(BaseModel):
    """Structured output for one collection iteration."""

    explore_tasks: list[str] = Field(
        default_factory=list,
        description="Disjoint readonly workspace search directives for this round (passed to explore).",
    )
    rationale: str = Field(
        default="",
        description="Brief note on what was gathered or what is still missing.",
    )
    finish_collection: bool = Field(
        description="Set true when findings are sufficient to draft the final plan.",
    )


class PlanRefinement(BaseModel):
    """Structured output for one plan-design iteration."""

    plan_markdown: str = Field(
        description="Current full markdown plan for the orchestrator (headings, ordered steps).",
    )
    rationale: str = Field(
        default="",
        description="What changed this round or why the plan is complete.",
    )
    finish_planning: bool = Field(
        description="Set true when the plan needs no further revision.",
    )


# --- Legacy structured models (retained for tests / external reuse) ---


class PlanStepDraft(BaseModel):
    """One step in a static plan decomposition (optional tooling)."""

    id: str = Field(description="Stable step id, e.g. S1, S2.")
    title: str = Field(default="", description="Short title for the step.")
    description: str = Field(description="What to do in this step.")
    request_explore: bool = Field(
        default=False,
        description="When true, run readonly workspace recon for this step before finalizing.",
    )
    explore_focus: str | None = Field(
        default=None,
        description="Natural-language focus passed to explore; defaults to description when empty.",
    )


class PlanDecomposition(BaseModel):
    """Structured plan (legacy single-shot decomposition)."""

    objective: str = Field(description="Restated objective in one or two sentences.")
    steps: list[PlanStepDraft] = Field(default_factory=list, description="Ordered execution steps.")
