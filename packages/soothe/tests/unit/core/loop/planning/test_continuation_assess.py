"""Tests for RFC-226 LLMPlanner.assess_continuation discriminator.

Mocks the LLM structured-output call and asserts:
- bootstrap action propagates reasoning + goal_progress
- plan_generate action propagates fields
- LLM exception → safe fallback to plan_generate
- Invalid LLM action → safe fallback to plan_generate
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from soothe.foundation.sloop.cognition.planner import LLMPlanner
from soothe.foundation.sloop.state.schemas import ContinuationAssessment


def _make_planner() -> LLMPlanner:
    """Construct an LLMPlanner with mocked model + config (sufficient for assess_continuation)."""
    model = MagicMock()
    # _plan_phase_chat_model returns a chat model; with_structured_output returns the structured wrapper.
    structured = MagicMock()
    model.with_structured_output = MagicMock(return_value=structured)
    # _plan_phase_chat_model is a module-level function; let it pass through `model`.
    planner = LLMPlanner.__new__(LLMPlanner)
    planner._model = model
    planner._config = None
    planner._loop_id = "loop-test"
    return planner


@pytest.mark.asyncio
async def test_continuation_assess_bootstrap() -> None:
    planner = _make_planner()
    expected = ContinuationAssessment(
        action="bootstrap",
        reasoning="Translate prior result; no new tools.",
        goal_progress="low",
    )

    with patch(
        "soothe.foundation.sloop.cognition.planner._plan_phase_chat_model",
        return_value=planner._model,
    ):
        structured = planner._model.with_structured_output.return_value
        structured.ainvoke = AsyncMock(return_value=expected)

        result = await planner.assess_continuation(
            current_goal="translate the result to chinese",
            prior_goals=[
                {
                    "goal_id": "g0",
                    "goal_text": "count files",
                    "completion": "There are 12 file types.",
                    "step_count": 1,
                    "current_plan_action": "",
                }
            ],
            capabilities=["read_file", "run_python"],
        )

    assert result.action == "bootstrap"
    assert "Translate" in result.reasoning
    assert result.goal_progress == "low"


@pytest.mark.asyncio
async def test_continuation_assess_plan_generate() -> None:
    planner = _make_planner()
    expected = ContinuationAssessment(
        action="plan_generate",
        reasoning="New tools (email) required.",
        goal_progress="none",
    )

    with patch(
        "soothe.foundation.sloop.cognition.planner._plan_phase_chat_model",
        return_value=planner._model,
    ):
        structured = planner._model.with_structured_output.return_value
        structured.ainvoke = AsyncMock(return_value=expected)

        result = await planner.assess_continuation(
            current_goal="translate the result and email to bob",
            prior_goals=[
                {
                    "goal_id": "g0",
                    "goal_text": "count files",
                    "completion": "There are 12 file types.",
                    "step_count": 1,
                    "current_plan_action": "",
                }
            ],
            capabilities=["read_file", "send_email"],
        )

    assert result.action == "plan_generate"
    assert "email" in result.reasoning


@pytest.mark.asyncio
async def test_continuation_assess_llm_exception_falls_back_to_plan_generate() -> None:
    planner = _make_planner()

    with patch(
        "soothe.foundation.sloop.cognition.planner._plan_phase_chat_model",
        return_value=planner._model,
    ):
        structured = planner._model.with_structured_output.return_value
        structured.ainvoke = AsyncMock(side_effect=RuntimeError("LLM provider down"))

        result = await planner.assess_continuation(
            current_goal="translate",
            prior_goals=[
                {
                    "goal_id": "g0",
                    "goal_text": "count",
                    "completion": "12",
                    "step_count": 1,
                    "current_plan_action": "",
                }
            ],
            capabilities=[],
        )

    assert result.action == "plan_generate"
    assert "fallback" in result.reasoning.lower() or "failed" in result.reasoning.lower()


@pytest.mark.asyncio
async def test_continuation_assess_invalid_action_falls_back() -> None:
    planner = _make_planner()

    class _BogusResult:
        action = "nonsense"
        reasoning = "x"
        goal_progress = "none"

    with patch(
        "soothe.foundation.sloop.cognition.planner._plan_phase_chat_model",
        return_value=planner._model,
    ):
        structured = planner._model.with_structured_output.return_value
        structured.ainvoke = AsyncMock(return_value=_BogusResult())

        result = await planner.assess_continuation(
            current_goal="translate",
            prior_goals=[
                {
                    "goal_id": "g0",
                    "goal_text": "count",
                    "completion": "12",
                    "step_count": 1,
                    "current_plan_action": "",
                }
            ],
            capabilities=[],
        )

    assert result.action == "plan_generate"
