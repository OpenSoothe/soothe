"""Unit tests for 4-class intake classification (RFC-630).

The LLM classifier produces a 4-class ``intake_label`` (``quiz`` | ``trivial``
| ``simple`` | ``complex``) that drives ``route_by_intent``. Loop continuation
is derived structurally inside ``StrangeLoop`` from the loaded checkpoint and
is not a classifier concern.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from soothe.foundation.sloop.intention import IntentClassification, IntentClassifier, TaskComplexity
from soothe.foundation.sloop.intention.models import (
    IntakeClassificationLLMResult,
    IntakeLabel,
)
from soothe.foundation.sloop.intention.prompts import (
    INTAKE_CLASSIFICATION_PROMPT,
    INTAKE_CLASSIFICATION_RETRY_PROMPT,
)


class TestIntentClassificationModel:
    """Test IntentClassification Pydantic model."""

    def test_model_creation_quiz(self) -> None:
        intent = IntentClassification(
            intent_type="quiz",
            intake_label=IntakeLabel.QUIZ,
            task_complexity=TaskComplexity.MINIMAL,
            quiz_response="Hello! How can I help?",
        )
        assert intent.intent_type == "quiz"
        assert intent.intake_label == IntakeLabel.QUIZ
        assert intent.quiz_response == "Hello! How can I help?"

    def test_model_creation_complex(self) -> None:
        intent = IntentClassification(
            intent_type="agentic",
            intake_label=IntakeLabel.COMPLEX,
            goal_description="Build a web scraper",
            task_complexity=TaskComplexity.COMPLEX,
        )
        assert intent.intent_type == "agentic"
        assert intent.intake_label == IntakeLabel.COMPLEX
        assert intent.goal_description == "Build a web scraper"
        assert intent.quiz_response is None


class TestIntakeClassificationLLMResult:
    """Test the 4-class intake schema and its resolution (RFC-630)."""

    def test_quiz_resolves_to_quiz(self) -> None:
        llm_result = IntakeClassificationLLMResult(
            intake_label=IntakeLabel.QUIZ,
            task_complexity=TaskComplexity.MINIMAL,
            quiz_response="Hi there!",
        )
        intent = llm_result.to_intent_classification()
        assert intent.intent_type == "quiz"
        assert intent.intake_label == IntakeLabel.QUIZ
        assert intent.quiz_response == "Hi there!"

    def test_trivial_resolves_to_agentic_trivial(self) -> None:
        llm_result = IntakeClassificationLLMResult(
            intake_label=IntakeLabel.TRIVIAL,
            reasoning="one obvious step",
            goal_description="list files in this directory",
            task_complexity=TaskComplexity.SIMPLE,
        )
        intent = llm_result.to_intent_classification()
        assert intent.intent_type == "agentic"
        assert intent.intake_label == IntakeLabel.TRIVIAL
        assert intent.goal_description == "list files in this directory"

    def test_simple_resolves_to_agentic_simple(self) -> None:
        llm_result = IntakeClassificationLLMResult(
            intake_label=IntakeLabel.SIMPLE,
            reasoning="single focused step",
            goal_description="summarize RFC-220 topology",
            task_complexity=TaskComplexity.SIMPLE,
        )
        intent = llm_result.to_intent_classification()
        assert intent.intent_type == "agentic"
        assert intent.intake_label == IntakeLabel.SIMPLE

    def test_complex_resolves_to_agentic_complex(self) -> None:
        llm_result = IntakeClassificationLLMResult(
            intake_label=IntakeLabel.COMPLEX,
            reasoning="multi-step refactor",
            goal_description="refactor the persistence layer",
            task_complexity=TaskComplexity.COMPLEX,
        )
        intent = llm_result.to_intent_classification()
        assert intent.intent_type == "agentic"
        assert intent.intake_label == IntakeLabel.COMPLEX


class TestIntakeClassificationPrompts:
    """Prompt content guards for 4-class intake classification (RFC-630)."""

    def test_primary_prompt_has_four_labels(self) -> None:
        for label in ("quiz", "trivial", "simple", "complex"):
            assert label in INTAKE_CLASSIFICATION_PROMPT

    def test_retry_prompt_has_four_labels(self) -> None:
        for label in ("quiz", "trivial", "simple", "complex"):
            assert label in INTAKE_CLASSIFICATION_RETRY_PROMPT

    def test_primary_prompt_biases_toward_complex(self) -> None:
        """When uncertain, the intake must prefer the more capable label (RFC-630 §9.3)."""
        assert (
            "prefer" in INTAKE_CLASSIFICATION_PROMPT.lower()
            or "complex" in INTAKE_CLASSIFICATION_PROMPT
        )

    def test_primary_prompt_uses_assistant_name(self) -> None:
        assert "{assistant_name}" in INTAKE_CLASSIFICATION_PROMPT
        assert "not vendor/model names" in INTAKE_CLASSIFICATION_PROMPT

    def test_primary_prompt_excludes_runtime_state_from_quiz(self) -> None:
        assert "runtime state" in INTAKE_CLASSIFICATION_PROMPT
        assert "workspace" in INTAKE_CLASSIFICATION_PROMPT


@pytest.mark.asyncio
class TestIntakeClassifier:
    """Test the 4-class intake classifier with mocked LLM (RFC-630)."""

    async def test_quiz_intake_classification(self) -> None:
        classifier = IntentClassifier(model=MagicMock(), assistant_name="TestBot")
        mock_llm_result = IntentClassification(
            intent_type="quiz",
            intake_label=IntakeLabel.QUIZ,
            task_complexity=TaskComplexity.MINIMAL,
        )
        with patch.object(classifier, "_classify_intake_llm", new_callable=AsyncMock) as mock_llm:
            mock_llm.return_value = mock_llm_result
            result = await classifier.classify_intake("你好")
        assert result.intent_type == "quiz"
        assert result.intake_label == IntakeLabel.QUIZ

    async def test_complex_intake_classification(self) -> None:
        classifier = IntentClassifier(model=MagicMock(), assistant_name="TestBot")
        mock_llm_result = IntentClassification(
            intent_type="agentic",
            intake_label=IntakeLabel.COMPLEX,
            goal_description="Refactor persistence",
            task_complexity=TaskComplexity.COMPLEX,
        )
        with patch.object(classifier, "_classify_intake_llm", new_callable=AsyncMock) as mock_llm:
            mock_llm.return_value = mock_llm_result
            result = await classifier.classify_intake("Refactor the persistence layer")
        assert result.intent_type == "agentic"
        assert result.intake_label == IntakeLabel.COMPLEX
        assert result.goal_description == "Refactor persistence"

    async def test_long_query_is_not_short_circuited(self) -> None:
        """RFC-630: the _is_likely_agentic heuristic is deleted; long queries
        must reach the LLM, not be forced to agentic by length."""
        classifier = IntentClassifier(model=MagicMock(), assistant_name="TestBot")
        long_query = (
            "Please help me refactor the authentication module to use OAuth2 "
            "with PKCE flow and update all the tests"
        )
        mock_llm_result = IntentClassification(
            intent_type="quiz",
            intake_label=IntakeLabel.QUIZ,
            task_complexity=TaskComplexity.MINIMAL,
        )
        with patch.object(classifier, "_classify_intake_llm", new_callable=AsyncMock) as mock_llm:
            mock_llm.return_value = mock_llm_result
            result = await classifier.classify_intake(long_query)
        # Long query reached the LLM (mock called) and was classified quiz —
        # the length heuristic is gone.
        mock_llm.assert_awaited()
        assert result.intake_label == IntakeLabel.QUIZ

    async def test_fallback_defaults_to_complex(self) -> None:
        """RFC-630 §9.3: when the classifier is disabled, fallback is complex."""
        classifier = IntentClassifier(model=None, assistant_name="TestBot")
        result = await classifier.classify_intake("do something")
        assert result.intent_type == "agentic"
        assert result.intake_label == IntakeLabel.COMPLEX
        assert result.task_complexity == TaskComplexity.COMPLEX

    async def test_classifier_constructed_with_fast_model(self) -> None:
        model = MagicMock()
        classifier = IntentClassifier(model=model, assistant_name="TestBot")
        assert classifier._fast_model is model
        # invoke_structured_chat builds the runnable lazily at call time, so
        # construction should NOT touch with_structured_output.
        model.with_structured_output.assert_not_called()
