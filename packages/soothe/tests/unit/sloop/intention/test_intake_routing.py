"""Integration tests for intake classification (RFC-630 / RFC-904)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from langgraph.graph import END

from soothe.sloop.intention import (
    IntakeConfidence,
    IntakeCoordinator,
    IntakeLabel,
    IntakeLLMResult,
)
from soothe.sloop.orchestrator.routing import route_by_intent


def create_mock_coordinator(
    *,
    is_task: bool,
    confidence: str = "high",
    social_response: str | None = None,
    intake_reasoning: str = "test",
) -> IntakeCoordinator:
    mock_model = MagicMock()
    coordinator = IntakeCoordinator(mock_model)
    intake_result = IntakeLLMResult(
        is_task=is_task,
        confidence=IntakeConfidence(confidence),
        social_response=social_response,
        reasoning=intake_reasoning,
    )
    coordinator._intake_classifier.classify = AsyncMock(return_value=intake_result)
    return coordinator


@pytest.mark.asyncio
async def test_task_intake_skips_scope_preclassification() -> None:
    coordinator = create_mock_coordinator(is_task=True, confidence="high")
    result = await coordinator.classify("fix the flaky test")
    assert result.is_task is True
    assert result.intake_label == IntakeLabel.COMPLEX
    assert result.intent_classification is not None


@pytest.mark.asyncio
async def test_social_intake_routes_to_chitchat() -> None:
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
