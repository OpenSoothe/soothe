"""Tests for 3-class intake classification (RFC-630)."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from soothe.foundation.sloop.intention import IntentClassification, IntentClassifier, TaskComplexity
from soothe.foundation.sloop.intention.models import (
    IntakeClassificationLLMResult,
    IntakeLabel,
    derive_task_complexity_from_intake,
)
from soothe.foundation.sloop.intention.prompts import (
    INTAKE_CLASSIFICATION_RETRY_SYSTEM_PROMPT,
    INTAKE_CLASSIFICATION_SYSTEM_PROMPT,
)


class TestIntentClassificationModel:
    """Test IntentClassification Pydantic model."""

    def test_model_creation_trivial(self) -> None:
        intent = IntentClassification(
            intake_label=IntakeLabel.TRIVIAL,
            task_complexity=TaskComplexity.MINIMAL,
        )
        assert intent.intent_type == "agentic"
        assert intent.intake_label == IntakeLabel.TRIVIAL

    def test_model_creation_complex(self) -> None:
        intent = IntentClassification(
            intake_label=IntakeLabel.COMPLEX,
            goal_description="Build a web scraper",
            task_complexity=TaskComplexity.COMPLEX,
        )
        assert intent.intent_type == "agentic"
        assert intent.intake_label == IntakeLabel.COMPLEX
        assert intent.goal_description == "Build a web scraper"


class TestDeriveTaskComplexityFromIntake:
    """``task_complexity`` is derived from ``intake_label``, not LLM output."""

    def test_trivial_maps_to_minimal(self) -> None:
        assert derive_task_complexity_from_intake(IntakeLabel.TRIVIAL) == TaskComplexity.MINIMAL

    def test_simple_maps_to_simple(self) -> None:
        assert derive_task_complexity_from_intake(IntakeLabel.SIMPLE) == TaskComplexity.SIMPLE

    def test_complex_maps_to_complex(self) -> None:
        assert derive_task_complexity_from_intake(IntakeLabel.COMPLEX) == TaskComplexity.COMPLEX


class TestIntakeClassificationLLMResult:
    """Test the 3-class intake schema and its resolution (RFC-630)."""

    def test_trivial_resolves_to_agentic_trivial(self) -> None:
        llm_result = IntakeClassificationLLMResult(
            intake_label=IntakeLabel.TRIVIAL,
            reasoning="I'll greet you back.",
            goal_description="hello",
        )
        intent = llm_result.to_intent_classification()
        assert intent.intent_type == "agentic"
        assert intent.intake_label == IntakeLabel.TRIVIAL
        assert intent.task_complexity == TaskComplexity.MINIMAL

    def test_simple_resolves_to_agentic_simple(self) -> None:
        llm_result = IntakeClassificationLLMResult(
            intake_label=IntakeLabel.SIMPLE,
            reasoning="single focused step",
            goal_description="summarize RFC-220 topology",
        )
        intent = llm_result.to_intent_classification()
        assert intent.intent_type == "agentic"
        assert intent.intake_label == IntakeLabel.SIMPLE
        assert intent.task_complexity == TaskComplexity.SIMPLE

    def test_complex_resolves_to_agentic_complex(self) -> None:
        llm_result = IntakeClassificationLLMResult(
            intake_label=IntakeLabel.COMPLEX,
            reasoning="multi-step refactor",
            goal_description="refactor the persistence layer",
        )
        intent = llm_result.to_intent_classification()
        assert intent.intent_type == "agentic"
        assert intent.intake_label == IntakeLabel.COMPLEX
        assert intent.task_complexity == TaskComplexity.COMPLEX


class TestIntakeClassificationPrompts:
    """Prompt content guards for 3-class intake classification (RFC-630)."""

    def test_primary_prompt_has_three_labels(self) -> None:
        for label in ("trivial", "simple", "complex"):
            assert label in INTAKE_CLASSIFICATION_SYSTEM_PROMPT
        assert "quiz" not in INTAKE_CLASSIFICATION_SYSTEM_PROMPT

    def test_retry_prompt_has_three_labels(self) -> None:
        for label in ("trivial", "simple", "complex"):
            assert label in INTAKE_CLASSIFICATION_RETRY_SYSTEM_PROMPT

    def test_primary_prompt_omits_quiz_response(self) -> None:
        assert "quiz_response" not in INTAKE_CLASSIFICATION_SYSTEM_PROMPT

    def test_primary_prompt_biases_toward_complex(self) -> None:
        assert (
            "prefer" in INTAKE_CLASSIFICATION_SYSTEM_PROMPT.lower()
            or "complex" in INTAKE_CLASSIFICATION_SYSTEM_PROMPT
        )

    def test_primary_prompt_uses_assistant_name(self) -> None:
        from soothe.foundation.sloop.intention.intake_messages import build_intake_system_message

        system = build_intake_system_message("TestBot")
        assert "TestBot" in system

    def test_primary_prompt_omits_task_complexity(self) -> None:
        assert "task_complexity" not in INTAKE_CLASSIFICATION_SYSTEM_PROMPT

    def test_human_envelope_uses_goal_and_task(self) -> None:
        from soothe.foundation.sloop.intention.intake_messages import build_intake_human_message

        human = build_intake_human_message(query="summarize readme")
        assert human.startswith("GOAL:\nsummarize readme")
        assert "TASK:" in human


@pytest.mark.asyncio
class TestIntakeClassifier:
    """Test the 3-class intake classifier with mocked LLM (RFC-630)."""

    async def test_trivial_intake_classification(self) -> None:
        classifier = IntentClassifier(model=MagicMock(), assistant_name="TestBot")
        mock_llm_result = IntentClassification(
            intake_label=IntakeLabel.TRIVIAL,
            task_complexity=TaskComplexity.MINIMAL,
        )
        with patch.object(classifier, "_classify_intake_llm", new_callable=AsyncMock) as mock_llm:
            mock_llm.return_value = (mock_llm_result, "human", {"intake_label": "trivial"})
            result = await classifier.classify_intake("你好")
        assert result.intent_type == "agentic"
        assert result.intake_label == IntakeLabel.TRIVIAL

    async def test_weather_query_skips_llm_via_heuristic(self) -> None:
        classifier = IntentClassifier(model=MagicMock(), assistant_name="TestBot")
        with patch.object(classifier, "_classify_intake_llm", new_callable=AsyncMock) as mock_llm:
            result = await classifier.classify_intake("北京今天的天气")
        mock_llm.assert_not_called()
        assert result.intake_label == IntakeLabel.TRIVIAL

    async def test_complex_intake_classification(self) -> None:
        classifier = IntentClassifier(model=MagicMock(), assistant_name="TestBot")
        mock_llm_result = IntentClassification(
            intake_label=IntakeLabel.COMPLEX,
            goal_description="Refactor persistence",
            task_complexity=TaskComplexity.COMPLEX,
        )
        with patch.object(classifier, "_classify_intake_llm", new_callable=AsyncMock) as mock_llm:
            mock_llm.return_value = (
                mock_llm_result,
                "human",
                {"intake_label": "complex", "goal_description": "Refactor persistence"},
            )
            result = await classifier.classify_intake("Refactor the persistence layer")
        assert result.intake_label == IntakeLabel.COMPLEX
        assert result.goal_description == "Refactor persistence"

    async def test_long_query_reaches_llm(self) -> None:
        classifier = IntentClassifier(model=MagicMock(), assistant_name="TestBot")
        long_query = (
            "Please help me refactor the authentication module to use OAuth2 "
            "with PKCE flow and update all the tests"
        )
        mock_llm_result = IntentClassification(
            intake_label=IntakeLabel.TRIVIAL,
            task_complexity=TaskComplexity.MINIMAL,
        )
        with patch.object(classifier, "_classify_intake_llm", new_callable=AsyncMock) as mock_llm:
            mock_llm.return_value = (mock_llm_result, "human", {"intake_label": "trivial"})
            result = await classifier.classify_intake(long_query)
        mock_llm.assert_awaited()
        assert result.intake_label == IntakeLabel.TRIVIAL

    async def test_fallback_defaults_to_complex(self) -> None:
        classifier = IntentClassifier(model=None, assistant_name="TestBot")
        result = await classifier.classify_intake("do something")
        assert result.intake_label == IntakeLabel.COMPLEX
        assert result.task_complexity == TaskComplexity.COMPLEX
        assert result.reasoning is not None

    async def test_patch_missing_reasoning_uses_first_person(self) -> None:
        classifier = IntentClassifier(model=MagicMock(), assistant_name="TestBot")
        mock_llm_result = IntentClassification(
            intake_label=IntakeLabel.SIMPLE,
            goal_description="summarize readme",
            task_complexity=TaskComplexity.SIMPLE,
            reasoning=None,
        )
        with patch.object(classifier, "_classify_intake_llm", new_callable=AsyncMock) as mock_llm:
            mock_llm.return_value = (
                mock_llm_result,
                "human",
                {"intake_label": "simple", "goal_description": "summarize readme"},
            )
            result = await classifier.classify_intake("summarize readme")
        assert result.reasoning == "I'll use tools to work through this goal."
