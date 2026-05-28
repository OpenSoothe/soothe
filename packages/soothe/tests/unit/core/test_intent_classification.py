"""Unit tests for intent classification (RFC-225).

The LLM classifier produces only ``quiz`` or ``agentic``. Loop
continuation is derived structurally inside ``AgentLoop`` from the
loaded checkpoint and is not a classifier concern.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from soothe.core.intention import IntentClassification, IntentClassifier, TaskComplexity
from soothe.core.intention.models import IntentClassificationLLMResult
from soothe.core.intention.prompts import (
    INTENT_CLASSIFICATION_PROMPT,
    INTENT_CLASSIFICATION_RETRY_PROMPT,
)


class TestIntentClassificationModel:
    """Test IntentClassification Pydantic model."""

    def test_model_creation_quiz_greeting(self) -> None:
        intent = IntentClassification(
            intent_type="quiz",
            goal_description=None,
            task_complexity=TaskComplexity.MINIMAL,
            quiz_response="Hello! How can I help?",
        )
        assert intent.intent_type == "quiz"
        assert intent.quiz_response == "Hello! How can I help?"

    def test_model_creation_agentic(self) -> None:
        intent = IntentClassification(
            intent_type="agentic",
            goal_description="Build a web scraper",
            task_complexity=TaskComplexity.COMPLEX,
            quiz_response=None,
        )
        assert intent.intent_type == "agentic"
        assert intent.goal_description == "Build a web scraper"
        assert intent.quiz_response is None


class TestIntentClassificationLLMResult:
    """Test the LLM result schema and its resolution to IntentClassification."""

    def test_quiz_resolves_to_quiz(self) -> None:
        llm_result = IntentClassificationLLMResult(
            intent_type="quiz",
            goal_description=None,
            task_complexity=TaskComplexity.MINIMAL,
        )
        intent = llm_result.to_intent_classification()
        assert intent.intent_type == "quiz"
        assert intent.quiz_response is None

    def test_agentic_resolves_to_agentic(self) -> None:
        llm_result = IntentClassificationLLMResult(
            intent_type="agentic",
            goal_description="Refactor auth module",
            task_complexity=TaskComplexity.COMPLEX,
        )
        intent = llm_result.to_intent_classification()
        assert intent.intent_type == "agentic"
        assert intent.goal_description == "Refactor auth module"
        assert intent.quiz_response is None

    def test_quiz_piggybacks_response(self) -> None:
        llm_result = IntentClassificationLLMResult(
            intent_type="quiz",
            goal_description=None,
            task_complexity=TaskComplexity.MINIMAL,
            quiz_response="Shakespeare wrote Romeo and Juliet.",
        )
        intent = llm_result.to_intent_classification()
        assert intent.intent_type == "quiz"
        assert intent.quiz_response == "Shakespeare wrote Romeo and Juliet."

    def test_agentic_result_has_no_quiz_response(self) -> None:
        llm_result = IntentClassificationLLMResult(
            intent_type="agentic",
            goal_description="Build a scraper",
            task_complexity=TaskComplexity.MEDIUM,
            quiz_response=None,
        )
        intent = llm_result.to_intent_classification()
        assert intent.intent_type == "agentic"
        assert intent.quiz_response is None


class TestIntentClassificationPrompts:
    """Prompt content guards for quiz-only classification."""

    def test_primary_prompt_is_quiz_only(self) -> None:
        assert "quiz" in INTENT_CLASSIFICATION_PROMPT
        assert "agentic" in INTENT_CLASSIFICATION_PROMPT
        assert "continue_thread" not in INTENT_CLASSIFICATION_PROMPT
        assert "new_goal" not in INTENT_CLASSIFICATION_PROMPT
        assert "quiz_response" in INTENT_CLASSIFICATION_PROMPT

    def test_retry_prompt_is_quiz_only(self) -> None:
        assert "quiz" in INTENT_CLASSIFICATION_RETRY_PROMPT
        assert "agentic" in INTENT_CLASSIFICATION_RETRY_PROMPT
        assert "continue_thread" not in INTENT_CLASSIFICATION_RETRY_PROMPT
        assert "new_goal" not in INTENT_CLASSIFICATION_RETRY_PROMPT


@pytest.mark.asyncio
class TestIntentClassifier:
    """Test IntentClassifier with mocked LLM."""

    async def test_quiz_intent_classification(self) -> None:
        classifier = IntentClassifier(model=MagicMock(), assistant_name="TestBot")
        mock_llm_result = IntentClassification(
            intent_type="quiz",
            goal_description=None,
            task_complexity=TaskComplexity.MINIMAL,
            quiz_response=None,
        )
        with patch.object(classifier, "_classify_intent_llm", new_callable=AsyncMock) as mock_llm:
            mock_llm.return_value = mock_llm_result
            result = await classifier.classify_intent("你好")

        assert result.intent_type == "quiz"
        assert result.quiz_response is None

    async def test_agentic_intent_classification(self) -> None:
        classifier = IntentClassifier(model=MagicMock(), assistant_name="TestBot")
        mock_llm_result = IntentClassification(
            intent_type="agentic",
            goal_description="Look up Shanghai weather",
            task_complexity=TaskComplexity.SIMPLE,
        )
        with patch.object(classifier, "_classify_intent_llm", new_callable=AsyncMock) as mock_llm:
            mock_llm.return_value = mock_llm_result
            result = await classifier.classify_intent("上海的天气")

        assert result.intent_type == "agentic"
        assert result.quiz_response is None
        assert result.goal_description is not None

    async def test_quiz_vs_agentic_distinction(self) -> None:
        classifier = IntentClassifier(model=MagicMock(), assistant_name="TestBot")

        quiz_result = IntentClassification(
            intent_type="quiz",
            goal_description=None,
            task_complexity=TaskComplexity.MINIMAL,
        )
        with patch.object(classifier, "_classify_intent_llm", new_callable=AsyncMock) as mock_llm:
            mock_llm.return_value = quiz_result
            result = await classifier.classify_intent("Who wrote Romeo and Juliet?")
        assert result.intent_type == "quiz"
        assert result.task_complexity == TaskComplexity.MINIMAL

        agentic_result = IntentClassification(
            intent_type="agentic",
            goal_description="Refactor authentication module",
            task_complexity=TaskComplexity.MEDIUM,
        )
        with patch.object(classifier, "_classify_intent_llm", new_callable=AsyncMock) as mock_llm:
            mock_llm.return_value = agentic_result
            result = await classifier.classify_intent("Help me refactor authentication")
        assert result.intent_type == "agentic"

    async def test_classifier_uses_llm_result_schema(self) -> None:
        model = MagicMock()
        classifier = IntentClassifier(model=model, assistant_name="TestBot")
        assert classifier._intent_model is not None
        model.with_structured_output.assert_called_once()
        schema_arg = model.with_structured_output.call_args[0][0]
        assert schema_arg is IntentClassificationLLMResult

    async def test_fallback_defaults_to_agentic(self) -> None:
        """When the classifier is disabled, fallback is agentic."""
        classifier = IntentClassifier(model=None, assistant_name="TestBot")
        result = await classifier.classify_intent("do something")
        assert result.intent_type == "agentic"


class TestHeuristicClassification:
    """Test heuristic bypass for long/complex queries."""

    def test_short_query_is_not_agentic(self) -> None:
        assert not IntentClassifier._is_likely_agentic("hello")
        assert not IntentClassifier._is_likely_agentic("what is 2+2?")
        assert not IntentClassifier._is_likely_agentic("thanks")

    def test_long_query_is_agentic(self) -> None:
        long_query = "Please help me refactor the authentication module to use OAuth2 with PKCE flow and update all the tests"
        assert len(long_query) > 80
        assert IntentClassifier._is_likely_agentic(long_query)

    def test_many_words_is_agentic(self) -> None:
        many_words = "I want you to create a new feature that allows users to export their data as a CSV file"
        assert len(many_words.split()) > 15
        assert IntentClassifier._is_likely_agentic(many_words)

    def test_multiline_is_agentic(self) -> None:
        multiline = "First do this\nThen do that\nAnd also this"
        assert IntentClassifier._is_likely_agentic(multiline)

    @pytest.mark.asyncio
    async def test_heuristic_bypasses_llm(self) -> None:
        classifier = IntentClassifier(model=MagicMock(), assistant_name="TestBot")
        long_query = "Please help me refactor the authentication module to use OAuth2 with PKCE flow and update all the tests"
        result = await classifier.classify_intent(long_query)
        assert result.intent_type == "agentic"
        assert result.goal_description == long_query
