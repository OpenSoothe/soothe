"""Tests for RFC-226 LLMPlanner.assess_continuation discriminator.

Mocks the LLM structured-output call and asserts:
- bootstrap action propagates reasoning + goal_progress
- plan_generate action propagates fields
- LLM exception → safe fallback to plan_generate
- Invalid LLM action → safe fallback to plan_generate
- Full PRIOR GOAL COMPLETION body is injected into the prompt (not truncated)
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from soothe.foundation.sloop.cognition.continuation_prompts import (
    format_loop_continuation_assess_prompt,
)
from soothe.foundation.sloop.cognition.planner import LLMPlanner
from soothe.foundation.sloop.state.schemas import ContinuationAssessment


def _make_planner() -> LLMPlanner:
    """Construct an LLMPlanner with mocked model + config (sufficient for assess_continuation)."""
    model = MagicMock()
    structured = MagicMock()
    model.with_structured_output = MagicMock(return_value=structured)
    planner = LLMPlanner.__new__(LLMPlanner)
    planner._model = model
    planner._plan_assess_model = model
    planner._plan_generate_model = model
    planner._config = None
    planner._loop_id = "loop-test"
    return planner


def test_continuation_assess_prompt_injects_full_prior_goal_completion() -> None:
    body = "x" * 5000
    prompt = format_loop_continuation_assess_prompt(
        current_goal="continue",
        prior_goal_completion=body,
        capabilities=["read_file"],
    )
    assert "PRIOR GOAL COMPLETION:" in prompt
    assert body in prompt
    assert "completion=" not in prompt


@pytest.mark.asyncio
async def test_continuation_assess_bootstrap() -> None:
    planner = _make_planner()
    expected = ContinuationAssessment(
        action="bootstrap",
        reasoning="I'll translate the prior result without new tools.",
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
            prior_goal_completion="There are 12 file types in the project.",
            capabilities=["read_file", "run_python"],
        )

    assert result.action == "bootstrap"
    assert result.reasoning.startswith("I'll")
    assert result.goal_progress == "low"


@pytest.mark.asyncio
async def test_continuation_assess_plan_generate() -> None:
    planner = _make_planner()
    expected = ContinuationAssessment(
        action="plan_generate",
        reasoning="I need email tools to deliver the translated result.",
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
            prior_goal_completion="There are 12 file types.",
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
            prior_goal_completion="Prior completion body.",
            capabilities=[],
        )

    assert result.action == "plan_generate"
    assert result.reasoning.startswith("I'll")


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
            prior_goal_completion="Prior completion body.",
            capabilities=[],
        )

    assert result.action == "plan_generate"
    assert result.reasoning.startswith("I'll")
