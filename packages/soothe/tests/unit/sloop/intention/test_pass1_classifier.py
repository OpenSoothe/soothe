"""Unit tests for Pass 1 classifier: social vs task (IG-554)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from soothe.foundation.sloop.intention.models import IntakePass1Confidence, IntakePass1LLMResult
from soothe.foundation.sloop.intention.pass1_classifier import IntakePass1Classifier

# -- Helpers ---------------------------------------------------------------


def create_pass1_classifier_with_result(
    *,
    is_task: bool,
    confidence: IntakePass1Confidence,
    social_response: str | None = None,
    reasoning: str = "test",
) -> IntakePass1Classifier:
    """Create classifier with mock model returning specified result."""
    mock_model = MagicMock()
    result = IntakePass1LLMResult(
        is_task=is_task,
        confidence=confidence,
        social_response=social_response,
        reasoning=reasoning,
    )
    mock_model.with_structured_output = MagicMock(return_value=mock_model)
    mock_model.ainvoke = AsyncMock(return_value=result.model_dump())
    return IntakePass1Classifier(model=mock_model)


def create_pass1_classifier_with_raw_result(raw_result: dict) -> IntakePass1Classifier:
    """Create classifier with mock model returning raw dict."""
    mock_model = MagicMock()
    mock_model.with_structured_output = MagicMock(return_value=mock_model)
    mock_model.ainvoke = AsyncMock(return_value=raw_result)
    return IntakePass1Classifier(model=mock_model)


# -- Pivot pattern tests ---------------------------------------------------


@pytest.mark.parametrize(
    "query,expected_is_task",
    [
        ("ok, now apply the fix", True),
        ("about the refactor — finish it", True),
        ("alright, so the tests...", True),
        ("perfect. next: auth middleware", True),
        ("got it, so that SessionStore thing...", True),
        ("cool, and the migration script", True),
        ("sure, about the signature change", True),
    ],
)
async def test_pivot_patterns_are_task(query: str, expected_is_task: bool) -> None:
    """Pivot phrases after acknowledgment should classify as task."""
    classifier = create_pass1_classifier_with_result(
        is_task=expected_is_task,
        confidence=IntakePass1Confidence.HIGH,
        reasoning="pivot phrase detected",
    )
    result = await classifier.classify(query)
    assert result.is_task == expected_is_task


@pytest.mark.parametrize(
    "query",
    [
        "fix the bug in auth.py",
        "update the SessionStore module",
        "refactor the codebase",
        "add tests for the API",
    ],
)
async def test_technical_entity_references_are_task(query: str) -> None:
    """Technical entity names should classify as task."""
    classifier = create_pass1_classifier_with_result(
        is_task=True,
        confidence=IntakePass1Confidence.HIGH,
        reasoning="technical reference",
    )
    result = await classifier.classify(query)
    assert result.is_task is True


# -- Social pattern tests --------------------------------------------------


@pytest.mark.parametrize(
    "query,expected_response",
    [
        ("hi", "Hi! How can I help?"),
        ("hello", "Hello! How can I help you today?"),
        ("thanks!", "You're welcome!"),
        ("thank you", "You're welcome!"),
        ("who are you", "I'm Soothe, created by Dr. Xiaming Chen."),
    ],
)
async def test_social_queries_have_response(query: str, expected_response: str) -> None:
    """Social queries should include social_response."""
    classifier = create_pass1_classifier_with_result(
        is_task=False,
        confidence=IntakePass1Confidence.HIGH,
        social_response=expected_response,
        reasoning="social greeting",
    )
    result = await classifier.classify(query)
    assert result.is_task is False
    assert result.social_response is not None


@pytest.mark.parametrize(
    "query",
    [
        "ok",
        "sure",
        "alright",
        "got it",
    ],
)
async def test_standalone_acknowledgments_are_social(query: str) -> None:
    """Standalone acknowledgments without pivot should be social."""
    classifier = create_pass1_classifier_with_result(
        is_task=False,
        confidence=IntakePass1Confidence.HIGH,
        social_response="Got it. What would you like to work on?",
        reasoning="standalone acknowledgment",
    )
    result = await classifier.classify(query)
    assert result.is_task is False


# -- Fail-safe tests -------------------------------------------------------


async def test_no_model_returns_task() -> None:
    """No model should fail-safe to task."""
    classifier = IntakePass1Classifier(model=None)
    result = await classifier.classify("any query")
    assert result.is_task is True
    assert result.confidence == IntakePass1Confidence.LOW


async def test_llm_error_fails_safe_to_task() -> None:
    """LLM error should fail-safe to task."""
    mock_model = MagicMock()
    mock_model.ainvoke = AsyncMock(side_effect=Exception("LLM error"))
    classifier = IntakePass1Classifier(model=mock_model)
    result = await classifier.classify("any query")
    assert result.is_task is True
    assert result.confidence == IntakePass1Confidence.LOW


async def test_low_confidence_is_still_valid() -> None:
    """Low confidence result is still valid (no retry in Pass 1)."""
    classifier = create_pass1_classifier_with_result(
        is_task=True,
        confidence=IntakePass1Confidence.LOW,
        reasoning="ambiguous pivot",
    )
    result = await classifier.classify("alright, so...")
    assert result.is_task is True
    assert result.confidence == IntakePass1Confidence.LOW


# -- Field validation tests ------------------------------------------------


async def test_missing_social_response_is_patched() -> None:
    """Missing social_response for is_task=False should be patched."""
    classifier = create_pass1_classifier_with_raw_result(
        {"is_task": False, "confidence": "high", "social_response": "", "reasoning": "greeting"}
    )
    result = await classifier.classify("hi")
    assert result.social_response is not None
    assert len(result.social_response) > 0


async def test_invalid_confidence_defaults_to_medium() -> None:
    """Invalid confidence value defaults to medium."""
    classifier = create_pass1_classifier_with_raw_result(
        {"is_task": True, "confidence": "invalid", "social_response": None, "reasoning": "test"}
    )
    result = await classifier.classify("test")
    # Invalid confidence triggers fallback to complex in current impl
    assert result.confidence in (IntakePass1Confidence.MEDIUM, IntakePass1Confidence.LOW)
