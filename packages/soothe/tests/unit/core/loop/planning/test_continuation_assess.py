"""Tests for RFC-226 LLMPlanner.assess_continuation discriminator (IG-538 assembly)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from soothe_sdk.protocols.planner import PlanContext

from soothe.sloop.cognition.planner import LLMPlanner
from soothe.sloop.prompts import PromptBuilder
from soothe.sloop.state.schemas import ContinuationAssessment, LoopState


def _make_planner() -> LLMPlanner:
    """Construct an LLMPlanner with mocked model + PromptBuilder."""
    model = MagicMock()
    structured = MagicMock()
    model.with_structured_output = MagicMock(return_value=structured)
    planner = LLMPlanner.__new__(LLMPlanner)
    planner._model = model
    planner._plan_evaluate_assess_model = model
    planner._plan_generate_model = model
    planner._config = None
    planner._loop_id = "loop-test"
    planner._prompt_builder = PromptBuilder(None)
    return planner


def _state(*, goal: str = "translate the result to chinese") -> LoopState:
    return LoopState(goal=goal, thread_id="tid", continue_loop=True)


@pytest.mark.asyncio
async def test_continuation_assess_bootstrap() -> None:
    planner = _make_planner()
    expected = ContinuationAssessment(
        action="bootstrap",
        reasoning="I'll translate the prior result without new tools.",
        goal_progress="low",
    )

    with patch(
        "soothe.sloop.cognition.planner._plan_phase_chat_model",
        return_value=planner._model,
    ):
        structured = planner._model.with_structured_output.return_value
        structured.ainvoke = AsyncMock(return_value=expected)

        result = await planner.assess_continuation(
            state=_state(),
            context=PlanContext(available_capabilities=["read_file", "run_python"]),
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
        "soothe.sloop.cognition.planner._plan_phase_chat_model",
        return_value=planner._model,
    ):
        structured = planner._model.with_structured_output.return_value
        structured.ainvoke = AsyncMock(return_value=expected)

        result = await planner.assess_continuation(
            state=_state(goal="translate the result and email to bob"),
            context=PlanContext(available_capabilities=["read_file", "send_email"]),
        )

    assert result.action == "plan_generate"
    assert "email" in result.reasoning


@pytest.mark.asyncio
async def test_continuation_assess_llm_exception_falls_back_to_plan_generate() -> None:
    planner = _make_planner()

    with patch(
        "soothe.sloop.cognition.planner._plan_phase_chat_model",
        return_value=planner._model,
    ):
        structured = planner._model.with_structured_output.return_value
        structured.ainvoke = AsyncMock(side_effect=RuntimeError("LLM provider down"))

        result = await planner.assess_continuation(
            state=_state(goal="translate"),
            context=PlanContext(),
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
        "soothe.sloop.cognition.planner._plan_phase_chat_model",
        return_value=planner._model,
    ):
        structured = planner._model.with_structured_output.return_value
        structured.ainvoke = AsyncMock(return_value=_BogusResult())

        result = await planner.assess_continuation(
            state=_state(goal="translate"),
            context=PlanContext(),
        )

    assert result.action == "plan_generate"
    assert result.reasoning.startswith("I'll")


@pytest.mark.asyncio
async def test_continuation_assess_uses_unified_message_list() -> None:
    """Continuation assess builds system + ledger + task (not a lone HumanMessage)."""
    planner = _make_planner()
    captured: list[list] = []

    async def _capture_invoke(model, messages, schema, **kwargs):
        captured.append(messages)
        return ContinuationAssessment(
            action="bootstrap",
            reasoning="I'll answer from prior context.",
            goal_progress="low",
        )

    with patch(
        "soothe.sloop.cognition.planner._plan_phase_chat_model",
        return_value=planner._model,
    ):
        planner._invoke_structured = AsyncMock(side_effect=_capture_invoke)
        await planner.assess_continuation(
            state=_state(),
            context=PlanContext(),
        )

    assert len(captured) == 1
    assert len(captured[0]) >= 2
    last = captured[0][-1]
    assert "TASK:" in str(getattr(last, "content", ""))


@pytest.mark.asyncio
async def test_continuation_assess_guardrail_overrides_bootstrap_for_complex_intake() -> None:
    from soothe_sdk.intention.models import TaskComplexity

    from soothe.sloop.intention import IntentClassification
    from soothe.sloop.intention.models import IntakeLabel

    planner = _make_planner()
    state = _state(goal="run make docker-build then start docker and run e2e")
    state.intent = IntentClassification(
        intake_label=IntakeLabel.COMPLEX,
        task_complexity=TaskComplexity.COMPLEX,
    )
    expected = ContinuationAssessment(
        action="bootstrap",
        reasoning="",
        goal_progress="low",
    )

    with patch(
        "soothe.sloop.cognition.planner._plan_phase_chat_model",
        return_value=planner._model,
    ):
        planner._invoke_structured = AsyncMock(return_value=expected)
        result = await planner.assess_continuation(state=state, context=PlanContext())

    assert result.action == "plan_generate"
