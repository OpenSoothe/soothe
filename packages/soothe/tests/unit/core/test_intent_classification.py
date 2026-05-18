"""Unit tests for intent classification (IG-226, IG-250)."""

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
        """IntentClassification for merged quiz (greeting) query."""
        intent = IntentClassification(
            intent_type="quiz",
            reuse_current_goal=False,
            goal_description=None,
            task_complexity=TaskComplexity.MINIMAL,
            quiz_response="Hello! How can I help?",
        )
        assert intent.intent_type == "quiz"
        assert intent.reuse_current_goal is False
        assert intent.quiz_response == "Hello! How can I help?"

    def test_model_creation_continue_thread(self) -> None:
        """IntentClassification for continue_thread query."""
        intent = IntentClassification(
            intent_type="continue_thread",
            reuse_current_goal=True,
            goal_description=None,
            task_complexity=TaskComplexity.MEDIUM,
            quiz_response=None,
        )
        assert intent.intent_type == "continue_thread"
        assert intent.reuse_current_goal is True
        assert intent.quiz_response is None

    def test_model_creation_new_goal(self) -> None:
        """IntentClassification for new_goal query."""
        intent = IntentClassification(
            intent_type="new_goal",
            reuse_current_goal=False,
            goal_description="Build a web scraper",
            task_complexity=TaskComplexity.COMPLEX,
            quiz_response=None,
        )
        assert intent.intent_type == "new_goal"
        assert intent.goal_description == "Build a web scraper"
        assert intent.quiz_response is None

    def test_llm_result_to_intent_classification_clears_quiz_response(self) -> None:
        """LLM routing schema never carries quiz_response."""
        llm_result = IntentClassificationLLMResult(
            intent_type="quiz",
            reuse_current_goal=False,
            goal_description=None,
            task_complexity=TaskComplexity.MINIMAL,
        )
        intent = llm_result.to_intent_classification()
        assert intent.intent_type == "quiz"
        assert intent.quiz_response is None


class TestIntentClassificationPrompts:
    """Prompt content guards for routing-only classification."""

    def test_primary_prompt_excludes_quiz_response_and_covers_realtime(self) -> None:
        """Primary prompt is routing-only and excludes real-time quiz routing."""
        assert "quiz_response" not in INTENT_CLASSIFICATION_PROMPT
        assert "weather" in INTENT_CLASSIFICATION_PROMPT
        assert "unrelated to recent_conversation" in INTENT_CLASSIFICATION_PROMPT
        assert "Do not generate user-facing answers" in INTENT_CLASSIFICATION_PROMPT

    def test_retry_prompt_excludes_quiz_response(self) -> None:
        """Retry prompt matches routing-only schema."""
        assert "quiz_response" not in INTENT_CLASSIFICATION_RETRY_PROMPT
        assert "weather" in INTENT_CLASSIFICATION_RETRY_PROMPT


@pytest.mark.asyncio
class TestIntentClassifier:
    """Test IntentClassifier with mocked LLM."""

    @pytest.fixture
    def mock_fast_model(self) -> MagicMock:
        """Create mock fast model."""
        model = MagicMock()
        model.with_structured_output = MagicMock(return_value=model)
        return model

    @pytest.fixture
    def classifier(self, mock_fast_model: MagicMock) -> IntentClassifier:
        """Create IntentClassifier with mocked model."""
        return IntentClassifier(model=mock_fast_model, assistant_name="TestBot")

    async def test_quiz_intent_classification_routing_only(self) -> None:
        """LLM classifies greetings as quiz without piggybacked answer text."""
        classifier = IntentClassifier(model=MagicMock(), assistant_name="TestBot")

        mock_llm_result = IntentClassificationLLMResult(
            intent_type="quiz",
            reuse_current_goal=False,
            goal_description=None,
            task_complexity=TaskComplexity.MINIMAL,
        )

        with patch.object(classifier, "_classify_intent_llm", new_callable=AsyncMock) as mock_llm:
            mock_llm.return_value = mock_llm_result.to_intent_classification()
            result = await classifier.classify_intent("你好")

        assert result.intent_type == "quiz"
        assert result.quiz_response is None

    async def test_weather_classified_as_new_goal(self) -> None:
        """Real-time weather queries route to new_goal, not quiz."""
        classifier = IntentClassifier(model=MagicMock(), assistant_name="TestBot")

        mock_llm_result = IntentClassificationLLMResult(
            intent_type="new_goal",
            reuse_current_goal=False,
            goal_description="Look up Shanghai weather",
            friendly_message="I'll look up the current weather in Shanghai for you.",
            task_complexity=TaskComplexity.SIMPLE,
        )

        with patch.object(classifier, "_classify_intent_llm", new_callable=AsyncMock) as mock_llm:
            mock_llm.return_value = mock_llm_result.to_intent_classification()
            result = await classifier.classify_intent("上海的天气")

        assert result.intent_type == "new_goal"
        assert result.quiz_response is None
        assert result.goal_description is not None

    async def test_quiz_vs_new_goal_distinction(self) -> None:
        """Distinguish quiz from new_goal."""
        classifier = IntentClassifier(model=MagicMock(), assistant_name="TestBot")

        quiz_mock = IntentClassificationLLMResult(
            intent_type="quiz",
            reuse_current_goal=False,
            goal_description=None,
            task_complexity=TaskComplexity.MINIMAL,
        )

        with patch.object(classifier, "_classify_intent_llm", new_callable=AsyncMock) as mock_llm:
            mock_llm.return_value = quiz_mock.to_intent_classification()
            quiz_result = await classifier.classify_intent("Who wrote Romeo and Juliet?")
        assert quiz_result.intent_type == "quiz"
        assert quiz_result.quiz_response is None
        assert quiz_result.task_complexity == TaskComplexity.MINIMAL

        task_mock = IntentClassificationLLMResult(
            intent_type="new_goal",
            reuse_current_goal=False,
            goal_description="Refactor authentication module",
            task_complexity=TaskComplexity.MEDIUM,
        )

        with patch.object(classifier, "_classify_intent_llm", new_callable=AsyncMock) as mock_llm:
            mock_llm.return_value = task_mock.to_intent_classification()
            task_result = await classifier.classify_intent(
                "Help me refactor the entire authentication module with OAuth2"
            )
        assert task_result.intent_type == "new_goal"
        assert task_result.quiz_response is None

    async def test_quiz_math_question_routing_only(self) -> None:
        """Simple math questions classified as quiz without answer piggyback."""
        classifier = IntentClassifier(model=MagicMock(), assistant_name="TestBot")

        mock_llm_result = IntentClassificationLLMResult(
            intent_type="quiz",
            reuse_current_goal=False,
            goal_description=None,
            task_complexity=TaskComplexity.MINIMAL,
        )

        with patch.object(classifier, "_classify_intent_llm", new_callable=AsyncMock) as mock_llm:
            mock_llm.return_value = mock_llm_result.to_intent_classification()
            result = await classifier.classify_intent("What is 15 * 23?")

        assert result.intent_type == "quiz"
        assert result.quiz_response is None

    async def test_classifier_uses_llm_result_schema(self) -> None:
        """Structured output model uses routing-only LLM schema."""
        model = MagicMock()
        classifier = IntentClassifier(model=model, assistant_name="TestBot")
        assert classifier._intent_model is not None
        model.with_structured_output.assert_called_once()
        schema_arg = model.with_structured_output.call_args[0][0]
        assert schema_arg is IntentClassificationLLMResult
