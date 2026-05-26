"""Tests for structured plan parser (IG-433)."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from soothe.core.loop.planning.parser import parse_plan_from_text
from soothe.core.loop.planning.structured_plan_parser import (
    PlanExtracted,
    PlanStepExtracted,
    parse_plan_with_config,
)


class TestStructuredPlanParser:
    @pytest.mark.asyncio
    async def test_fallback_to_regex(self) -> None:
        text = "**Step 1: Setup**"
        plan = await parse_plan_with_config("Build app", text, model=None)
        assert len(plan.steps) >= 1

    @pytest.mark.asyncio
    async def test_structured_parse(self) -> None:
        mock_model = AsyncMock()
        extracted = PlanExtracted(
            goal="Build app",
            steps=[
                PlanStepExtracted(step_number=1, title="Setup", description="Install deps"),
                PlanStepExtracted(step_number=2, title="Run", depends_on=[1]),
            ],
        )
        structured = MagicMock()
        structured.ainvoke = AsyncMock(return_value=extracted)
        mock_model.with_structured_output = MagicMock(return_value=structured)

        from soothe.config.models import StructuredPlanConfig

        plan = await parse_plan_with_config(
            "Build app",
            "markdown plan",
            mock_model,
            config=StructuredPlanConfig(enabled=True),
        )
        assert plan.goal == "Build app"
        assert len(plan.steps) == 2
        assert plan.steps[1].depends_on == ["S_1"]

    def test_regex_still_works_sync(self) -> None:
        plan = parse_plan_from_text("Goal", "**Step 1: Alpha**")
        assert plan.steps[0].description == "Alpha"
