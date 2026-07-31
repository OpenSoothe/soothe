"""Planner structured-output method order (loop 7ea9 FC thrash)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from soothe_sdk.protocols.planner import PlanContext

from soothe.sloop.cognition import planner as planner_mod
from soothe.sloop.cognition.plan_generation_wire import (
    PlanGenerateStepWire,
    PlanGenerationWire,
)
from soothe.sloop.cognition.planner import LLMPlanner
from soothe.sloop.prompts import PromptBuilder
from soothe.sloop.state.schemas import (
    ContinuationAssessment,
    LoopState,
    StatusAssessment,
)


def _make_planner() -> LLMPlanner:
    model = MagicMock()
    structured = MagicMock()
    model.with_structured_output = MagicMock(return_value=structured)
    planner = LLMPlanner.__new__(LLMPlanner)
    planner._model = model
    planner._plan_assess_model = model
    planner._plan_generate_model = model
    planner._plan_gap_model = model
    planner._config = None
    planner._loop_id = "loop-test"
    planner._prompt_builder = PromptBuilder(None)
    return planner


@pytest.mark.asyncio
async def test_generate_plan_uses_json_schema_methods() -> None:
    """Fresh workers must not walk function_calling before json_schema."""
    planner = _make_planner()
    captured: dict[str, object] = {}

    async def _capture(*_args, **kwargs):
        captured.update(kwargs)
        return PlanGenerationWire(
            reasoning="I'll start with discovery.",
            steps=[PlanGenerateStepWire(description="Discover test runners")],
        )

    assessment = StatusAssessment(
        status="continue",
        goal_progress="none",
        assessment_reasoning="Need a plan.",
        require_goal_completion=False,
    )

    with patch(
        "soothe.sloop.cognition.planner._plan_phase_chat_model",
        return_value=planner._model,
    ):
        planner._invoke_structured = AsyncMock(side_effect=_capture)
        plan, _ = await planner._generate_plan_with_response(
            messages=[MagicMock()],
            assessment=assessment,
            goal="run tests",
            iteration=0,
            thread_id="tid",
        )

    assert plan.steps
    assert captured.get("methods") == planner_mod._PLANNER_JSON_METHODS
    assert captured["methods"] == ("json_schema", "json_mode")


@pytest.mark.asyncio
async def test_assess_status_uses_json_schema_methods() -> None:
    planner = _make_planner()
    captured: dict[str, object] = {}

    async def _capture(*_args, **kwargs):
        captured.update(kwargs)
        return StatusAssessment(
            status="continue",
            goal_progress="none",
            assessment_reasoning="Still open.",
            require_goal_completion=False,
        )

    with patch(
        "soothe.sloop.cognition.planner._plan_phase_chat_model",
        return_value=planner._model,
    ):
        planner._invoke_structured = AsyncMock(side_effect=_capture)
        assessment, _ = await planner._assess_status_with_response(
            messages=[MagicMock()],
            goal="run tests",
            iteration=0,
            thread_id="tid",
        )

    assert assessment.status == "continue"
    assert captured.get("methods") == ("json_schema", "json_mode")


@pytest.mark.asyncio
async def test_continuation_assess_uses_json_schema_methods() -> None:
    planner = _make_planner()
    captured: dict[str, object] = {}

    async def _capture(*_args, **kwargs):
        captured.update(kwargs)
        return ContinuationAssessment(
            action="bootstrap",
            reasoning="I'll answer from prior context.",
            goal_progress="low",
        )

    with patch(
        "soothe.sloop.cognition.planner._plan_phase_chat_model",
        return_value=planner._model,
    ):
        planner._invoke_structured = AsyncMock(side_effect=_capture)
        await planner.assess_continuation(
            state=LoopState(goal="translate prior result", thread_id="tid"),
            context=PlanContext(),
        )

    assert captured.get("methods") == ("json_schema", "json_mode")
