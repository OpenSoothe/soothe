"""Unit tests for intent classification (IG-226, IG-250).

Tests the quiz-only classifier. The LLM decides quiz vs agentic;
the runner resolves agentic into continue_thread or new_goal structurally.
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


class TestIntentClassificationLLMResult:
    """Test the LLM result schema and its resolution to IntentClassification."""

    def test_quiz_resolves_to_quiz(self) -> None:
        """LLM quiz result resolves to quiz regardless of continue_thread."""
        llm_result = IntentClassificationLLMResult(
            intent_type="quiz",
            goal_description=None,
            task_complexity=TaskComplexity.MINIMAL,
        )
        intent = llm_result.to_intent_classification(continue_thread=False)
        assert intent.intent_type == "quiz"
        assert intent.reuse_current_goal is False
        assert intent.quiz_response is None

    def test_agentic_resolves_to_new_goal_when_fresh_loop(self) -> None:
        """Agentic result resolves to new_goal for fresh loops."""
        llm_result = IntentClassificationLLMResult(
            intent_type="agentic",
            goal_description="Refactor auth module",
            task_complexity=TaskComplexity.COMPLEX,
        )
        intent = llm_result.to_intent_classification(continue_thread=False)
        assert intent.intent_type == "new_goal"
        assert intent.reuse_current_goal is False
        assert intent.goal_description == "Refactor auth module"

    def test_agentic_resolves_to_continue_thread_when_prior_goals(self) -> None:
        """Agentic result resolves to continue_thread for same-loop queries."""
        llm_result = IntentClassificationLLMResult(
            intent_type="agentic",
            goal_description="DUMP review to report",
            task_complexity=TaskComplexity.MEDIUM,
        )
        intent = llm_result.to_intent_classification(continue_thread=True)
        assert intent.intent_type == "continue_thread"
        assert intent.reuse_current_goal is True
        assert intent.goal_description == "DUMP review to report"

    def test_quiz_piggybacks_response(self) -> None:
        """Quiz result forwards piggybacked quiz_response."""
        llm_result = IntentClassificationLLMResult(
            intent_type="quiz",
            goal_description=None,
            task_complexity=TaskComplexity.MINIMAL,
            quiz_response="Shakespeare wrote Romeo and Juliet.",
        )
        intent = llm_result.to_intent_classification(continue_thread=False)
        assert intent.intent_type == "quiz"
        assert intent.quiz_response == "Shakespeare wrote Romeo and Juliet."

    def test_agentic_result_has_no_quiz_response(self) -> None:
        """Agentic result does not carry quiz_response."""
        llm_result = IntentClassificationLLMResult(
            intent_type="agentic",
            goal_description="Build a scraper",
            task_complexity=TaskComplexity.MEDIUM,
            quiz_response=None,
        )
        intent = llm_result.to_intent_classification(continue_thread=False)
        assert intent.intent_type == "new_goal"
        assert intent.quiz_response is None


class TestIntentClassificationPrompts:
    """Prompt content guards for quiz-only classification."""

    def test_primary_prompt_is_quiz_only(self) -> None:
        """Primary prompt uses quiz/agentic, not continue_thread/new_goal."""
        assert "quiz" in INTENT_CLASSIFICATION_PROMPT
        assert "agentic" in INTENT_CLASSIFICATION_PROMPT
        assert "continue_thread" not in INTENT_CLASSIFICATION_PROMPT
        assert "new_goal" not in INTENT_CLASSIFICATION_PROMPT
        assert "weather" in INTENT_CLASSIFICATION_PROMPT
        assert "quiz_response" in INTENT_CLASSIFICATION_PROMPT

    def test_retry_prompt_is_quiz_only(self) -> None:
        """Retry prompt uses quiz/agentic."""
        assert "quiz" in INTENT_CLASSIFICATION_RETRY_PROMPT
        assert "agentic" in INTENT_CLASSIFICATION_RETRY_PROMPT
        assert "continue_thread" not in INTENT_CLASSIFICATION_RETRY_PROMPT
        assert "new_goal" not in INTENT_CLASSIFICATION_RETRY_PROMPT


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

    async def test_quiz_intent_classification(self) -> None:
        """LLM classifies greetings as quiz."""
        classifier = IntentClassifier(model=MagicMock(), assistant_name="TestBot")

        mock_llm_result = IntentClassification(
            intent_type="quiz",
            reuse_current_goal=False,
            goal_description=None,
            task_complexity=TaskComplexity.MINIMAL,
            quiz_response=None,
        )

        with patch.object(classifier, "_classify_intent_llm", new_callable=AsyncMock) as mock_llm:
            mock_llm.return_value = mock_llm_result
            result = await classifier.classify_intent("你好")

        assert result.intent_type == "quiz"
        assert result.quiz_response is None

    async def test_agentic_resolves_to_new_goal_for_fresh_loop(self) -> None:
        """Agentic query in a fresh loop resolves to new_goal."""
        classifier = IntentClassifier(model=MagicMock(), assistant_name="TestBot")

        mock_llm_result = IntentClassification(
            intent_type="new_goal",
            reuse_current_goal=False,
            goal_description="Look up Shanghai weather",
            task_complexity=TaskComplexity.SIMPLE,
        )

        with patch.object(classifier, "_classify_intent_llm", new_callable=AsyncMock) as mock_llm:
            mock_llm.return_value = mock_llm_result
            result = await classifier.classify_intent("上海的天气", continue_thread=False)

        assert result.intent_type == "new_goal"
        assert result.quiz_response is None
        assert result.goal_description is not None

    async def test_agentic_resolves_to_continue_thread_with_prior_goals(self) -> None:
        """Agentic query with prior completed goals resolves to continue_thread."""
        classifier = IntentClassifier(model=MagicMock(), assistant_name="TestBot")

        mock_llm_result = IntentClassification(
            intent_type="continue_thread",
            reuse_current_goal=True,
            goal_description="DUMP review to report",
            task_complexity=TaskComplexity.MEDIUM,
        )

        with patch.object(classifier, "_classify_intent_llm", new_callable=AsyncMock) as mock_llm:
            mock_llm.return_value = mock_llm_result
            result = await classifier.classify_intent("DUMP review to report", continue_thread=True)

        assert result.intent_type == "continue_thread"
        assert result.reuse_current_goal is True

    async def test_quiz_vs_agentic_distinction(self) -> None:
        """Distinguish quiz from agentic."""
        classifier = IntentClassifier(model=MagicMock(), assistant_name="TestBot")

        quiz_result = IntentClassification(
            intent_type="quiz",
            reuse_current_goal=False,
            goal_description=None,
            task_complexity=TaskComplexity.MINIMAL,
        )

        with patch.object(classifier, "_classify_intent_llm", new_callable=AsyncMock) as mock_llm:
            mock_llm.return_value = quiz_result
            result = await classifier.classify_intent("Who wrote Romeo and Juliet?")
        assert result.intent_type == "quiz"
        assert result.task_complexity == TaskComplexity.MINIMAL

        agentic_result = IntentClassification(
            intent_type="new_goal",
            reuse_current_goal=False,
            goal_description="Refactor authentication module",
            task_complexity=TaskComplexity.MEDIUM,
        )

        with patch.object(classifier, "_classify_intent_llm", new_callable=AsyncMock) as mock_llm:
            mock_llm.return_value = agentic_result
            result = await classifier.classify_intent(
                "Help me refactor the entire authentication module with OAuth2"
            )
        assert result.intent_type == "new_goal"

    async def test_classifier_uses_llm_result_schema(self) -> None:
        """Structured output model uses routing-only LLM schema."""
        model = MagicMock()
        classifier = IntentClassifier(model=model, assistant_name="TestBot")
        assert classifier._intent_model is not None
        model.with_structured_output.assert_called_once()
        schema_arg = model.with_structured_output.call_args[0][0]
        assert schema_arg is IntentClassificationLLMResult

    async def test_fallback_defaults_to_new_goal_for_fresh_loop(self) -> None:
        """Fallback intent when classifier is disabled defaults to new_goal for fresh loop."""
        classifier = IntentClassifier(model=None, assistant_name="TestBot")
        result = await classifier.classify_intent("do something", continue_thread=False)
        assert result.intent_type == "new_goal"
        assert result.reuse_current_goal is False

    async def test_fallback_defaults_to_continue_thread_with_prior_goals(self) -> None:
        """Fallback intent when classifier is disabled defaults to continue_thread with prior goals."""
        classifier = IntentClassifier(model=None, assistant_name="TestBot")
        result = await classifier.classify_intent("do something", continue_thread=True)
        assert result.intent_type == "continue_thread"
        assert result.reuse_current_goal is True


class TestHeuristicClassification:
    """Test heuristic bypass for long/complex queries."""

    def test_short_query_is_not_agentic(self) -> None:
        """Short simple query is not classified as agentic by heuristic."""
        assert not IntentClassifier._is_likely_agentic("hello")
        assert not IntentClassifier._is_likely_agentic("what is 2+2?")
        assert not IntentClassifier._is_likely_agentic("thanks")

    def test_long_query_is_agentic(self) -> None:
        """Query over 80 chars is classified as agentic by heuristic."""
        long_query = "Please help me refactor the authentication module to use OAuth2 with PKCE flow and update all the tests"
        assert len(long_query) > 80
        assert IntentClassifier._is_likely_agentic(long_query)

    def test_many_words_is_agentic(self) -> None:
        """Query with over 15 words is classified as agentic by heuristic."""
        many_words = "I want you to create a new feature that allows users to export their data as a CSV file"
        assert len(many_words.split()) > 15
        assert IntentClassifier._is_likely_agentic(many_words)

    def test_multiline_is_agentic(self) -> None:
        """Query with 2+ lines is classified as agentic by heuristic."""
        multiline = "First do this\nThen do that\nAnd also this"
        assert IntentClassifier._is_likely_agentic(multiline)

    async def test_heuristic_bypasses_llm(self) -> None:
        """Long query skips LLM call entirely via heuristic."""
        classifier = IntentClassifier(model=MagicMock(), assistant_name="TestBot")
        long_query = "Please help me refactor the authentication module to use OAuth2 with PKCE flow and update all the tests"
        result = await classifier.classify_intent(long_query, continue_thread=False)
        assert result.intent_type == "new_goal"
        assert result.goal_description == long_query

    async def test_heuristic_respects_continue_thread(self) -> None:
        """Heuristic classification respects continue_thread flag."""
        classifier = IntentClassifier(model=MagicMock(), assistant_name="TestBot")
        long_query = "Please help me refactor the authentication module to use OAuth2 with PKCE flow and update all the tests"
        result = await classifier.classify_intent(long_query, continue_thread=True)
        assert result.intent_type == "continue_thread"
        assert result.reuse_current_goal is True
