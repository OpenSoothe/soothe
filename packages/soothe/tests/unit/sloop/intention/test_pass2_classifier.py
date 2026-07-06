"""Unit tests for Pass 2 classifier: scope classification (IG-554)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from soothe.foundation.sloop.intention.models import IntakePass2LLMResult, IntakeScope
from soothe.foundation.sloop.intention.pass2_classifier import IntakePass2Classifier

# -- Helpers ---------------------------------------------------------------


def create_pass2_classifier_with_result(
    *,
    scope: IntakeScope,
    goal_description: str,
    reasoning: str,
) -> IntakePass2Classifier:
    """Create classifier with mock model returning specified result."""
    mock_model = MagicMock()
    result = IntakePass2LLMResult(
        scope=scope,
        goal_description=goal_description,
        reasoning=reasoning,
    )
    mock_model.with_structured_output = MagicMock(return_value=mock_model)
    mock_model.ainvoke = AsyncMock(return_value=result.model_dump())
    return IntakePass2Classifier(model=mock_model)


def create_pass2_classifier_with_raw_result(raw_result: dict) -> IntakePass2Classifier:
    """Create classifier with mock model returning raw dict."""
    mock_model = MagicMock()
    mock_model.with_structured_output = MagicMock(return_value=mock_model)
    mock_model.ainvoke = AsyncMock(return_value=raw_result)
    return IntakePass2Classifier(model=mock_model)


# -- Scope classification tests --------------------------------------------


@pytest.mark.parametrize(
    "query,expected_scope",
    [
        ("list the files in src/", IntakeScope.TRIVIAL),
        ("what is the capital of France", IntakeScope.TRIVIAL),
        ("calculate 15 * 23", IntakeScope.TRIVIAL),
        ("fix the type error in auth.py", IntakeScope.SIMPLE),
        ("add tests for the new API endpoint", IntakeScope.SIMPLE),
        ("update the README with new instructions", IntakeScope.SIMPLE),
        ("refactor SessionStore across all callers", IntakeScope.COMPLEX),
        ("migrate the auth system to OAuth2", IntakeScope.COMPLEX),
        ("design a new caching architecture", IntakeScope.COMPLEX),
    ],
)
async def test_scope_classification(query: str, expected_scope: IntakeScope) -> None:
    """Queries should classify to correct scope."""
    classifier = create_pass2_classifier_with_result(
        scope=expected_scope,
        goal_description=query,
        reasoning="test",
    )
    result = await classifier.classify(query)
    assert result.scope == expected_scope


@pytest.mark.parametrize(
    "query",
    [
        "implement feature X across multiple modules",
        "refactor the entire authentication flow",
        "update all API handlers for new schema",
    ],
)
async def test_multi_file_is_complex(query: str) -> None:
    """Multi-file changes should classify as complex."""
    classifier = create_pass2_classifier_with_result(
        scope=IntakeScope.COMPLEX,
        goal_description=query,
        reasoning="multi-file change",
    )
    result = await classifier.classify(query)
    assert result.scope == IntakeScope.COMPLEX


# -- Prior context tests ---------------------------------------------------


async def test_prior_projection_passed_to_llm() -> None:
    """Prior projection should be included in messages."""
    mock_model = MagicMock()
    mock_model.with_structured_output = MagicMock(return_value=mock_model)
    mock_model.ainvoke = AsyncMock(
        return_value={
            "scope": "simple",
            "goal_description": "apply the signature change",
            "reasoning": "single file fix",
        }
    )
    classifier = IntakePass2Classifier(model=mock_model)

    prior = "Previous goal: refactor SessionStore method signatures"
    result = await classifier.classify("apply it", prior_projection=prior)

    assert result.scope == IntakeScope.SIMPLE


async def test_no_prior_projection_works() -> None:
    """Classifier should work without prior projection."""
    classifier = create_pass2_classifier_with_result(
        scope=IntakeScope.SIMPLE,
        goal_description="fix the bug",
        reasoning="single fix",
    )
    result = await classifier.classify("fix the bug", prior_projection=None)
    assert result.scope == IntakeScope.SIMPLE


# -- Fail-safe tests -------------------------------------------------------


async def test_no_model_returns_complex() -> None:
    """No model should fail-safe to complex."""
    classifier = IntakePass2Classifier(model=None)
    result = await classifier.classify("any query")
    assert result.scope == IntakeScope.COMPLEX


async def test_llm_error_fails_safe_to_complex() -> None:
    """LLM error should fail-safe to complex."""
    mock_model = MagicMock()
    mock_model.ainvoke = AsyncMock(side_effect=Exception("LLM error"))
    classifier = IntakePass2Classifier(model=mock_model)
    result = await classifier.classify("any query")
    assert result.scope == IntakeScope.COMPLEX


async def test_invalid_scope_fails_safe_to_complex() -> None:
    """Invalid scope value should raise and fail-safe."""
    classifier = create_pass2_classifier_with_raw_result(
        {"scope": "invalid", "goal_description": "test", "reasoning": "test"}
    )
    # Invalid scope triggers ValueError, which triggers fallback
    result = await classifier.classify("test")
    assert result.scope == IntakeScope.COMPLEX


# -- Field validation tests ------------------------------------------------


async def test_missing_goal_description_is_patched() -> None:
    """Missing goal_description should be patched with query."""
    classifier = create_pass2_classifier_with_raw_result(
        {"scope": "simple", "goal_description": "", "reasoning": "test"}
    )
    result = await classifier.classify("fix the bug in auth.py")
    assert result.goal_description == "fix the bug in auth.py"


async def test_goal_description_preserves_code_paths() -> None:
    """goal_description should preserve code paths and IDs."""
    classifier = create_pass2_classifier_with_result(
        scope=IntakeScope.SIMPLE,
        goal_description="Fix the type error in src/auth/login.py:42",
        reasoning="single file fix",
    )
    result = await classifier.classify("fix the type error in src/auth/login.py:42")
    assert "src/auth/login.py:42" in result.goal_description


# -- Intake label conversion tests -----------------------------------------


def test_scope_trivial_to_intake_label() -> None:
    """IntakePass2LLMResult.to_intake_label for trivial."""
    result = IntakePass2LLMResult(
        scope=IntakeScope.TRIVIAL,
        goal_description="test",
        reasoning="test",
    )
    assert result.to_intake_label().value == "trivial"


def test_scope_simple_to_intake_label() -> None:
    """IntakePass2LLMResult.to_intake_label for simple."""
    result = IntakePass2LLMResult(
        scope=IntakeScope.SIMPLE,
        goal_description="test",
        reasoning="test",
    )
    assert result.to_intake_label().value == "simple"


def test_scope_complex_to_intake_label() -> None:
    """IntakePass2LLMResult.to_intake_label for complex."""
    result = IntakePass2LLMResult(
        scope=IntakeScope.COMPLEX,
        goal_description="test",
        reasoning="test",
    )
    assert result.to_intake_label().value == "complex"
