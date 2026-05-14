"""Unit tests for intent classification (IG-226, IG-250)."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from soothe.core.intention import IntentClassification, IntentClassifier, TaskComplexity


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

        mock_result = IntentClassification(
            intent_type="quiz",
            reuse_current_goal=False,
            goal_description=None,
            task_complexity=TaskComplexity.MINIMAL,
            quiz_response="你好! 我是 Soothe。有什么可以帮你的吗?",
        )

        with patch.object(classifier, "_classify_intent_llm", new_callable=AsyncMock) as mock_llm:
            mock_llm.return_value = mock_result
            result = await classifier.classify_intent("你好")

        assert result.intent_type == "quiz"
        assert result.quiz_response is not None
        assert "你好" in result.quiz_response

    async def test_quiz_vs_new_goal_distinction(self) -> None:
        """Distinguish quiz from new_goal."""
        classifier = IntentClassifier(model=MagicMock(), assistant_name="TestBot")

        quiz_mock = IntentClassification(
            intent_type="quiz",
            reuse_current_goal=False,
            goal_description=None,
            task_complexity=TaskComplexity.MINIMAL,
            quiz_response="William Shakespeare wrote Romeo and Juliet.",
        )

        with patch.object(classifier, "_classify_intent_llm", new_callable=AsyncMock) as mock_llm:
            mock_llm.return_value = quiz_mock
            quiz_result = await classifier.classify_intent("Who wrote Romeo and Juliet?")
        assert quiz_result.intent_type == "quiz"
        assert quiz_result.quiz_response is not None
        assert quiz_result.task_complexity == TaskComplexity.MINIMAL

        task_mock = IntentClassification(
            intent_type="new_goal",
            reuse_current_goal=False,
            goal_description="Refactor authentication module",
            task_complexity=TaskComplexity.MEDIUM,
            quiz_response=None,
        )

        with patch.object(classifier, "_classify_intent_llm", new_callable=AsyncMock) as mock_llm:
            mock_llm.return_value = task_mock
            task_result = await classifier.classify_intent(
                "Help me refactor the entire authentication module with OAuth2"
            )
        assert task_result.intent_type == "new_goal"
        assert task_result.quiz_response is None

    async def test_quiz_math_question(self) -> None:
        """Simple math questions classified as quiz."""
        classifier = IntentClassifier(model=MagicMock(), assistant_name="TestBot")

        mock_result = IntentClassification(
            intent_type="quiz",
            reuse_current_goal=False,
            goal_description=None,
            task_complexity=TaskComplexity.MINIMAL,
            quiz_response="15 * 23 = 345",
        )

        with patch.object(classifier, "_classify_intent_llm", new_callable=AsyncMock) as mock_llm:
            mock_llm.return_value = mock_result
            result = await classifier.classify_intent("What is 15 * 23?")

        assert result.intent_type == "quiz"
        assert result.quiz_response is not None

    async def test_patching_missing_quiz_response(self) -> None:
        """Classifier patches missing quiz_response for quiz intent."""
        classifier = IntentClassifier(model=MagicMock(), assistant_name="TestBot")

        mock_result = IntentClassification(
            intent_type="quiz",
            reuse_current_goal=False,
            goal_description=None,
            task_complexity=TaskComplexity.MINIMAL,
            quiz_response=None,
        )

        with patch.object(classifier, "_classify_intent_llm", new_callable=AsyncMock) as mock_llm:
            mock_llm.return_value = mock_result
            result = await classifier.classify_intent("Hello")

        assert result.intent_type == "quiz"
        assert result.quiz_response is not None
        assert "TestBot" in result.quiz_response
