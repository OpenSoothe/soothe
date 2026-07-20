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
