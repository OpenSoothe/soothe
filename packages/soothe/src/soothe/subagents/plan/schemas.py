"""Pydantic schemas for the plan subagent (RFC-618)."""

from __future__ import annotations

from pydantic import BaseModel, Field


class PlanSubagentConfig(BaseModel):
    """YAML configuration under ``subagents.planner.config``."""

    max_plan_rounds: int = Field(
        default=5,
        ge=1,
        le=24,
        description="Maximum agentic plan-design iterations before the draft is emitted.",
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


class PlanDecomposition(BaseModel):
    """Structured plan (legacy single-shot decomposition)."""

    objective: str = Field(description="Restated objective in one or two sentences.")
    steps: list[PlanStepDraft] = Field(default_factory=list, description="Ordered execution steps.")
