"""Raw-message fallback when plan-assess structured tool output is null."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from soothe.foundation.sloop.cognition.planner import (
    LLMPlanner,
    _parse_status_assessment_from_raw_message,
)
from soothe.foundation.sloop.state.schemas import StatusAssessment
from soothe.utils.llm.structured import StructuredOutputError


def test_parse_status_assessment_from_reasoning_content() -> None:
    payload = {
        "status": "done",
        "goal_progress": "complete",
        "assessment_reasoning": "Directory listing is complete.",
        "require_goal_completion": False,
    }
    msg = AIMessage(content="", additional_kwargs={"reasoning_content": json.dumps(payload)})
    assessment = _parse_status_assessment_from_raw_message(msg)
    assert assessment.status == "done"
    assert assessment.goal_progress == "complete"


@pytest.mark.asyncio
async def test_assess_status_recovers_done_when_structured_invoke_fails() -> None:
    """Thinking models may return valid JSON in reasoning while tool json is null."""
    planner = LLMPlanner(MagicMock())
    mock_model = MagicMock()
    mock_model.bind = MagicMock(return_value=mock_model)
    planner._model = mock_model
    planner._plan_assess_model = mock_model

    done_payload = {
        "status": "done",
        "goal_progress": "complete",
        "assessment_reasoning": "I see the directory listing is complete.",
        "require_goal_completion": False,
    }
    mock_model.ainvoke = AsyncMock(
        return_value=AIMessage(
            content="",
            additional_kwargs={"reasoning_content": json.dumps(done_payload)},
        )
    )

    with patch(
        "soothe.foundation.sloop.cognition.planner._invoke_plan_structured_output",
        new_callable=AsyncMock,
        side_effect=StructuredOutputError("structured tool json was null"),
    ):
        assessment, ai_response = await planner._assess_status_with_response(
            [HumanMessage(content="assess")],
            "list dirs of current workspace",
            1,
            thread_id="t1",
        )

    assert isinstance(assessment, StatusAssessment)
    assert assessment.status == "done"
    assert assessment.goal_progress == "complete"
    assert ai_response is assessment
    mock_model.ainvoke.assert_awaited_once()


@pytest.mark.asyncio
async def test_assess_status_retries_status_only_structured_output() -> None:
    """Status-only assess output should trigger one corrective structured retry."""
    planner = LLMPlanner(MagicMock())
    mock_model = MagicMock()
    mock_model.bind = MagicMock(return_value=mock_model)
    planner._model = mock_model
    planner._plan_assess_model = mock_model

    planner._invoke_structured = AsyncMock(  # type: ignore[method-assign]
        side_effect=[
            StatusAssessment(status="replan"),
            StatusAssessment(
                status="replan",
                goal_progress="medium",
                assessment_reasoning="I'll replan from the verified evidence.",
            ),
        ]
    )

    assessment, ai_response = await planner._assess_status_with_response(
        [HumanMessage(content="assess")],
        "rename file and fix links",
        1,
        thread_id="t1",
    )

    assert isinstance(assessment, StatusAssessment)
    assert assessment.status == "replan"
    assert assessment.goal_progress == "medium"
    assert ai_response is assessment
    assert planner._invoke_structured.await_count == 2  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_assess_status_coerces_after_status_only_retry() -> None:
    """Repeated status-only assess output should be coerced away from none."""
    planner = LLMPlanner(MagicMock())
    mock_model = MagicMock()
    mock_model.bind = MagicMock(return_value=mock_model)
    planner._model = mock_model
    planner._plan_assess_model = mock_model

    planner._invoke_structured = AsyncMock(  # type: ignore[method-assign]
        side_effect=[
            StatusAssessment(status="replan"),
            StatusAssessment(status="replan"),
        ]
    )

    assessment, ai_response = await planner._assess_status_with_response(
        [HumanMessage(content="assess")],
        "rename file and fix links",
        1,
        thread_id="t1",
    )

    assert isinstance(assessment, StatusAssessment)
    assert assessment.status == "replan"
    assert assessment.goal_progress == "low"
    assert "omitted required fields" in assessment.assessment_reasoning
    assert ai_response is assessment
