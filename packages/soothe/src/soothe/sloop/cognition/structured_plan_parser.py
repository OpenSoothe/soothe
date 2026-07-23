"""Structured LLM plan parsing (IG-433)."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Literal

from pydantic import BaseModel, Field
from soothe_nano.utils.llm.invoke_policy import (
    await_with_llm_call_policy,
    llm_rate_limit_config_from,
)
from soothe_nano.utils.llm.structured import invoke_structured_chat_typed
from soothe_sdk.protocols.planner import Plan, PlanStep

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
    from soothe_sdk.observability.langfuse import SootheLangfuse

    from soothe.prompts.fragments import STRUCTURED_PLAN_PARSE_PROMPT_FRAGMENT

    prompt = STRUCTURED_PLAN_PARSE_PROMPT_FRAGMENT.format(
        goal=goal,
        planner_output=planner_output[:12000],
    )
    invoke_config = (
        SootheLangfuse(soothe_config).traced_llm(
            purpose="structured_plan_parse",
            component="loop.cognition.structured_parser",
            phase="plan-generate",
            run_name="soothe:structured-plan-parse",
        )
        if soothe_config is not None
        else {}
    )

    async def _invoke() -> PlanExtracted:
        return await invoke_structured_chat_typed(
            model,
            [HumanMessage(content=prompt)],
            PlanExtracted,
            config=invoke_config,
        )

    extracted = await await_with_llm_call_policy(
        _invoke,
        config=llm_rate_limit_config_from(soothe_config),
    )
    if not extracted.goal:
        extracted = extracted.model_copy(update={"goal": goal})
    return plan_extracted_to_plan(extracted)
