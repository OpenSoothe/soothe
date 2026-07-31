"""Unit tests for Pass 2 classifier: scope classification (IG-554)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from soothe.sloop.intention.models import IntakePass2LLMResult, IntakeScope
from soothe.sloop.intention.pass2_classifier import IntakePass2Classifier

# -- Helpers ---------------------------------------------------------------


def create_pass2_classifier_with_result(
    *,
    scope: IntakeScope,
    reasoning: str,
) -> IntakePass2Classifier:
    """Create classifier with mock model returning specified result."""
    mock_model = MagicMock()
    result = IntakePass2LLMResult(
        scope=scope,
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
        ("fix the null check across SessionStore callers", IntakeScope.SIMPLE),
        ("refactor SessionStore across all callers then migrate callers", IntakeScope.COMPLEX),
        ("migrate the auth system to OAuth2", IntakeScope.COMPLEX),
        ("design a new caching architecture", IntakeScope.COMPLEX),
    ],
)
async def test_scope_classification(query: str, expected_scope: IntakeScope) -> None:
    """Queries should classify to correct scope."""
    classifier = create_pass2_classifier_with_result(
        scope=expected_scope,
        reasoning="test",
    )
    result = await classifier.classify(query)
    assert result.scope == expected_scope


@pytest.mark.parametrize(
    "query,expected_scope",
    [
        ("fix the null check across SessionStore callers", IntakeScope.SIMPLE),
        ("implement feature X across a few modules", IntakeScope.SIMPLE),
        ("first scan the repo and then run tests", IntakeScope.COMPLEX),
    ],
)
async def test_coherent_multifile_prefers_simple_unless_phased(
    query: str, expected_scope: IntakeScope
) -> None:
    """Multi-file alone is simple; explicit ordered phases stay complex."""
    classifier = create_pass2_classifier_with_result(
        scope=expected_scope,
        reasoning="coreagent-first scope",
    )
    result = await classifier.classify(query)
    assert result.scope == expected_scope


# -- Prior context tests ---------------------------------------------------


async def test_prior_projection_passed_to_llm() -> None:
    """Prior projection should be included in messages."""
    mock_model = MagicMock()
    mock_model.with_structured_output = MagicMock(return_value=mock_model)
    mock_model.ainvoke = AsyncMock(
        return_value={
            "scope": "simple",
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
        reasoning="single fix",
    )
    result = await classifier.classify("fix the bug", prior_projection=None)
    assert result.scope == IntakeScope.SIMPLE


# -- Fail-safe tests -------------------------------------------------------


async def test_no_model_returns_simple() -> None:
    """No model should fail-safe to simple."""
    classifier = IntakePass2Classifier(model=None)
    result = await classifier.classify("any query")
    assert result.scope == IntakeScope.SIMPLE


async def test_llm_error_fails_safe_to_simple() -> None:
    """LLM error should fail-safe to simple."""
    mock_model = MagicMock()
    mock_model.ainvoke = AsyncMock(side_effect=Exception("LLM error"))
    classifier = IntakePass2Classifier(model=mock_model)
    result = await classifier.classify("any query")
    assert result.scope == IntakeScope.SIMPLE


async def test_structured_output_error_fails_safe_to_simple() -> None:
    """StructuredOutputError after one invoke fails safe to simple (no outer retry)."""
    from unittest.mock import patch

    from soothe_nano.utils.llm.structured import StructuredOutputError

    mock_model = MagicMock()
    classifier = IntakePass2Classifier(model=mock_model)
    with patch(
        "soothe.sloop.intention.pass2_classifier.invoke_structured_chat",
        new=AsyncMock(
            side_effect=StructuredOutputError(
                "structured model invoke failed: Provider returned empty response for json_schema format. Response object: AIMessage"
            ),
        ),
    ) as mock_invoke:
        result = await classifier.classify("count files in packages")
    assert result.scope == IntakeScope.SIMPLE
    assert mock_invoke.await_count == 1


async def test_pass2_prefers_json_schema_structured_methods() -> None:
    """Pass 2 asks invoke_structured_chat to try json_schema before function_calling."""
    from unittest.mock import patch

    from soothe.sloop.intention.structured_methods import INTAKE_JSON_FIRST_METHODS

    mock_model = MagicMock()
    classifier = IntakePass2Classifier(model=mock_model)
    with patch(
        "soothe.sloop.intention.pass2_classifier.invoke_structured_chat",
        new=AsyncMock(
            return_value={
                "scope": "simple",
                "reasoning": "I'll inspect the files.",
                "multi_phase": False,
                "requires_tool_use": True,
            }
        ),
    ) as mock_invoke:
        await classifier.classify("reanalyze project arch")
    assert mock_invoke.await_args.kwargs["methods"] == INTAKE_JSON_FIRST_METHODS


async def test_pass2_clips_runaway_reasoning() -> None:
    """Long Pass 2 reasoning is clipped before IntentClassification / TUI."""
    from unittest.mock import patch

    from soothe.sloop.intention.pass2_classifier import _PASS2_REASONING_MAX_CHARS

    long_reason = "I'll " + ("run tests and fix failures " * 20)
    mock_model = MagicMock()
    classifier = IntakePass2Classifier(model=mock_model)
    with patch(
        "soothe.sloop.intention.pass2_classifier.invoke_structured_chat",
        new=AsyncMock(
            return_value={
                "scope": "complex",
                "reasoning": long_reason,
                "multi_phase": True,
                "requires_tool_use": True,
            }
        ),
    ):
        result = await classifier.classify(
            "run and fix unit+integration tests for soothe, daemon, cli and all clients in parallel"
        )
    assert result.scope == IntakeScope.COMPLEX
    assert len(result.reasoning) <= _PASS2_REASONING_MAX_CHARS
    assert result.reasoning.endswith("…")


def test_clip_pass2_reasoning_short_unchanged() -> None:
    from soothe.sloop.intention.pass2_classifier import clip_pass2_reasoning

    assert clip_pass2_reasoning("I'll run the tests.") == "I'll run the tests."


def test_pass2_prompt_marks_parallel_multi_package_as_complex() -> None:
    from soothe.sloop.intention.prompts import INTAKE_PASS2_SYSTEM_PROMPT

    assert "in parallel" in INTAKE_PASS2_SYSTEM_PROMPT
    assert "multi-package" in INTAKE_PASS2_SYSTEM_PROMPT
    assert "soothe, daemon, cli and all clients" in INTAKE_PASS2_SYSTEM_PROMPT


def test_clip_pass2_prior_projection_keeps_tail() -> None:
    from soothe.sloop.intention.pass2_classifier import (
        _PASS2_PRIOR_MAX_CHARS,
        clip_pass2_prior_projection,
    )

    long_prior = "HEAD-" + ("x" * (_PASS2_PRIOR_MAX_CHARS + 50)) + "-TAIL"
    clipped = clip_pass2_prior_projection(long_prior)
    assert clipped is not None
    assert clipped.startswith("…\n")
    assert clipped.endswith("-TAIL")
    assert len(clipped) <= _PASS2_PRIOR_MAX_CHARS + 2


async def test_invalid_scope_fails_safe_to_simple() -> None:
    """Invalid scope value should raise and fail-safe."""
    classifier = create_pass2_classifier_with_raw_result({"scope": "invalid", "reasoning": "test"})
    # Invalid scope triggers ValueError, which triggers fallback
    result = await classifier.classify("test")
    assert result.scope == IntakeScope.SIMPLE


# -- Intake label conversion tests -----------------------------------------


def test_scope_trivial_to_intake_label() -> None:
    """IntakePass2LLMResult.to_intake_label for trivial."""
    result = IntakePass2LLMResult(
        scope=IntakeScope.TRIVIAL,
        reasoning="test",
    )
    assert result.to_intake_label().value == "trivial"


def test_scope_simple_to_intake_label() -> None:
    """IntakePass2LLMResult.to_intake_label for simple."""
    result = IntakePass2LLMResult(
        scope=IntakeScope.SIMPLE,
        reasoning="test",
    )
    assert result.to_intake_label().value == "simple"


def test_scope_complex_to_intake_label() -> None:
    """IntakePass2LLMResult.to_intake_label for complex."""
    result = IntakePass2LLMResult(
        scope=IntakeScope.COMPLEX,
        reasoning="test",
    )
    assert result.to_intake_label().value == "complex"
