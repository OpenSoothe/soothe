"""Integration tests for Pass 1 intake (RFC-630 / RFC-904)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from langgraph.graph import END

from soothe.sloop.intention import (
    IntakeLabel,
    IntakePass1Confidence,
    IntakePass1LLMResult,
    TwoPassIntakeCoordinator,
)
from soothe.sloop.orchestrator.routing import route_by_intent


def create_mock_coordinator(
    *,
    is_task: bool,
    confidence: str = "high",
    social_response: str | None = None,
    pass1_reasoning: str = "test",
) -> TwoPassIntakeCoordinator:
    mock_model = MagicMock()
    coordinator = TwoPassIntakeCoordinator(mock_model)
    pass1_result = IntakePass1LLMResult(
        is_task=is_task,
        confidence=IntakePass1Confidence(confidence),
        social_response=social_response,
        reasoning=pass1_reasoning,
    )
    coordinator._pass1_classifier.classify = AsyncMock(return_value=pass1_result)
    return coordinator


@pytest.mark.asyncio
async def test_pass1_task_skips_pass2() -> None:
    coordinator = create_mock_coordinator(is_task=True, confidence="high")
    result = await coordinator.classify("fix the flaky test")
    assert result.is_task is True
    assert result.scope is None
    assert result.intake_label == IntakeLabel.COMPLEX
    assert result.intent_classification is not None


@pytest.mark.asyncio
async def test_pass1_greeting_routes_to_social() -> None:
    coordinator = create_mock_coordinator(
        is_task=False,
        confidence="high",
        social_response="Hello!",
    )
    result = await coordinator.classify("hi")
    assert result.is_social is True
    assert result.intake_label == IntakeLabel.CHITCHAT


def test_route_task_goes_to_dispatch() -> None:
    assert (
        route_by_intent({"intent_route": "continue_loop", "intake_label": IntakeLabel.COMPLEX})
        == "dispatch"
    )


def test_route_fast_path_ends() -> None:
    assert route_by_intent({"intent_route": "fast_path"}) is END


def test_route_wired_subagent() -> None:
    assert route_by_intent({"intent_route": "wired_subagent"}) == "delegate"
