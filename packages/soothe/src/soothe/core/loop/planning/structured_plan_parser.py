"""Structured LLM plan parsing (IG-433)."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Literal

from pydantic import BaseModel, Field

from soothe.config.models import StructuredPlanConfig
from soothe.core.loop.planning.parser import parse_plan_from_text
from soothe.protocols.planner import Plan, PlanStep

if TYPE_CHECKING:
    from langchain_core.language_models import BaseChatModel

logger = logging.getLogger(__name__)


class PlanStepExtracted(BaseModel):
    """Single plan step from structured LLM extraction."""

    step_number: int = Field(ge=1)
    title: str
    description: str | None = None
    depends_on: list[int] = Field(default_factory=list)
    estimated_complexity: Literal["low", "medium", "high"] | None = None


class PlanExtracted(BaseModel):
    """Structured plan extraction result."""

    goal: str
    steps: list[PlanStepExtracted] = Field(min_length=1)


def plan_extracted_to_plan(extracted: PlanExtracted) -> Plan:
    """Convert structured extraction to ``Plan`` protocol model."""
    steps = [
        PlanStep(
            id=f"S_{item.step_number}",
            description=item.description or item.title,
            depends_on=[f"S_{dep}" for dep in item.depends_on if dep > 0],
        )
        for item in extracted.steps
    ]
    return Plan(goal=extracted.goal, steps=steps)


async def parse_plan_structured(
    goal: str,
    planner_output: str,
    model: BaseChatModel,
    *,
    soothe_config: Any | None = None,
) -> Plan:
    """Use LLM structured output to extract a plan from planner markdown/text."""
    from langchain_core.messages import HumanMessage

    from soothe.utils.observability.langfuse import build_traced_config

    prompt = (
        "Extract an execution plan from the planner output below.\n"
        f"Goal: {goal}\n\n"
        f"Planner output:\n{planner_output[:12000]}\n\n"
        "Return ordered steps with step_number starting at 1. "
        "Use depends_on for step numbers that must complete first."
    )
    invoke_config = build_traced_config(
        soothe_config,
        purpose="structured_plan_parse",
        component="loop.planning.structured_parser",
        phase="plan-generate",
        run_name="soothe:structured-plan-parse",
    )
    structured = model.with_structured_output(PlanExtracted)
    result = await structured.ainvoke([HumanMessage(content=prompt)], config=invoke_config)
    extracted = (
        result if isinstance(result, PlanExtracted) else PlanExtracted.model_validate(result)
    )
    if not extracted.goal:
        extracted = extracted.model_copy(update={"goal": goal})
    return plan_extracted_to_plan(extracted)


async def parse_plan_with_config(
    goal: str,
    text: str,
    model: BaseChatModel | None,
    *,
    config: StructuredPlanConfig | None = None,
    soothe_config: Any | None = None,
) -> Plan:
    """Parse plan using structured LLM path when enabled, else regex heuristics."""
    cfg = config or StructuredPlanConfig()
    if cfg.enabled and model is not None and text.strip():
        try:
            return await parse_plan_structured(goal, text, model, soothe_config=soothe_config)
        except Exception:
            logger.warning("Structured plan parse failed, falling back to regex", exc_info=True)
    return parse_plan_from_text(goal, text)
