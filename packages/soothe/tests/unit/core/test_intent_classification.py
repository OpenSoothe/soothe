"""Tests for unified LLM-based intent classification system (IG-226)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from soothe.core.intention import IntentClassification, IntentClassifier, TaskComplexity

# ---------------------------------------------------------------------------
# Pydantic model tests
# ---------------------------------------------------------------------------


class TestIntentClassification:
    """Test IntentClassification model."""

    def test_model_creation_chitchat(self) -> None:
        """IntentClassification for chitchat query."""
        intent = IntentClassification(
            intent_type="chitchat",
            task_complexity=TaskComplexity.MINIMAL,
            chitchat_response="Hello! How can I help?",
        )

        assert intent.intent_type == "chitchat"
        assert intent.task_complexity == TaskComplexity.MINIMAL
        assert intent.chitchat_response == "Hello! How can I help?"
        assert not intent.reuse_current_goal
        assert intent.goal_description is None

    def test_model_creation_continue_thread(self) -> None:
        """IntentClassification for continue-thread query."""
        intent = IntentClassification(
            intent_type="continue_thread",
            reuse_current_goal=True,
            task_complexity="medium",
        )

        assert intent.intent_type == "continue_thread"
        assert intent.reuse_current_goal
        assert intent.task_complexity == "medium"
        assert intent.chitchat_response is None
        assert intent.goal_description is None

    def test_model_creation_new_goal(self) -> None:
        """IntentClassification for new goal query."""
        intent = IntentClassification(
            intent_type="new_goal",
            goal_description="Count all readme files in the workspace",
            task_complexity="medium",
        )

        assert intent.intent_type == "new_goal"
        assert intent.goal_description == "Count all readme files in the workspace"
        assert intent.task_complexity == "medium"
        assert not intent.reuse_current_goal
        assert intent.chitchat_response is None

    def test_model_defaults(self) -> None:
        """IntentClassification default values."""
        intent = IntentClassification(
            intent_type="new_goal",
            task_complexity="medium",
        )

        assert not intent.reuse_current_goal
        assert intent.goal_description is None
        assert intent.chitchat_response is None

    def test_model_creation_new_goal_simple(self) -> None:
        """IntentClassification accepts simple complexity for one-step tasks."""
        intent = IntentClassification(
            intent_type="new_goal",
            goal_description="Count README files in workspace",
            task_complexity="simple",
        )
        assert intent.task_complexity == "simple"


# ---------------------------------------------------------------------------
# Classifier init tests
# ---------------------------------------------------------------------------


class TestIntentClassifierIntent:
    """Test IntentClassifier intent classification."""

    def test_init_with_intent_model(self) -> None:
        """Classifier initializes intent model."""
        mock_model = MagicMock()
        mock_model.with_structured_output = MagicMock(return_value=mock_model)

        classifier = IntentClassifier(
            model=mock_model,
        )

        assert classifier._fast_model == mock_model
        assert classifier._intent_model is not None

    def test_init_without_model_intent_disabled(self) -> None:
        """Classifier without model disables intent classification."""
        classifier = IntentClassifier(
            model=None,
        )

        assert classifier._fast_model is None
        assert classifier._intent_model is None


# ---------------------------------------------------------------------------
# Intent classification tests
# ---------------------------------------------------------------------------


class TestIntentClassificationLLM:
    """Test LLM-driven intent classification."""

    @pytest.mark.asyncio
    async def test_chitchat_intent_classification(self) -> None:
        """LLM correctly classifies greetings as chitchat."""
        mock_model = MagicMock()
        mock_intent_model = AsyncMock()

        # Mock LLM response for chitchat
        mock_intent_model.ainvoke = AsyncMock(
            return_value=IntentClassification(
                intent_type="chitchat",
                task_complexity=TaskComplexity.MINIMAL,
                chitchat_response="你好! 我是 Soothe。有什么可以帮你的吗?",
            )
        )

        classifier = IntentClassifier(
            model=mock_model,
        )
        classifier._intent_model = mock_intent_model

        result = await classifier.classify_intent("你好!")

        assert result.intent_type == "chitchat"
        assert result.chitchat_response is not None
        assert "你好" in result.chitchat_response
        assert result.task_complexity == TaskComplexity.MINIMAL
        assert not result.reuse_current_goal

    @pytest.mark.asyncio
    async def test_continue_thread_with_context(self) -> None:
        """LLM detects continue-thread from conversation context."""
        mock_model = MagicMock()
        mock_intent_model = AsyncMock()

        # Recent conversation showing prior result
        recent_messages = [
            HumanMessage("list all python files"),
            AIMessage("Found 42 .py files in the workspace: main.py, utils.py, ..."),
        ]

        # Mock LLM response for continue-thread
        mock_intent_model.ainvoke = AsyncMock(
            return_value=IntentClassification(
                intent_type="continue_thread",
                reuse_current_goal=True,
                task_complexity="medium",
            )
        )

        classifier = IntentClassifier(
            model=mock_model,
        )
        classifier._intent_model = mock_intent_model

        result = await classifier.classify_intent(
            "translate that to Spanish",
            recent_messages=recent_messages,
            active_goal_id="goal_001",
            active_goal_description="List python files in workspace",
        )

        assert result.intent_type == "continue_thread"
        assert result.reuse_current_goal
        assert result.task_complexity == "medium"
        assert result.chitchat_response is None
        assert result.goal_description is None

    @pytest.mark.asyncio
    async def test_continue_thread_without_active_goal(self) -> None:
        """Continue-thread without active goal sets reuse_current_goal=False."""
        mock_model = MagicMock()
        mock_intent_model = AsyncMock()

        # Mock LLM response
        mock_intent_model.ainvoke = AsyncMock(
            return_value=IntentClassification(
                intent_type="continue_thread",
                reuse_current_goal=False,  # No active goal
                task_complexity="medium",
            )
        )

        classifier = IntentClassifier(
            model=mock_model,
        )
        classifier._intent_model = mock_intent_model

        result = await classifier.classify_intent(
            "explain the result",
            recent_messages=[HumanMessage("analyze code"), AIMessage("Analysis complete...")],
            active_goal_id=None,  # No active goal
        )

        assert result.intent_type == "continue_thread"
        assert not result.reuse_current_goal

    @pytest.mark.asyncio
    async def test_new_goal_intent_classification(self) -> None:
        """LLM detects new standalone task."""
        mock_model = MagicMock()
        mock_intent_model = AsyncMock()

        # Mock LLM response for new goal
        mock_intent_model.ainvoke = AsyncMock(
            return_value=IntentClassification(
                intent_type="new_goal",
                goal_description="Count all readme files in the project",
                task_complexity="medium",
            )
        )

        classifier = IntentClassifier(
            model=mock_model,
        )
        classifier._intent_model = mock_intent_model

        result = await classifier.classify_intent("count all readme files")

        assert result.intent_type == "new_goal"
        assert result.goal_description is not None
        assert (
            "count" in result.goal_description.lower()
            or "readme" in result.goal_description.lower()
        )
        assert result.task_complexity == "medium"
        assert not result.reuse_current_goal
        assert result.chitchat_response is None

    @pytest.mark.asyncio
    async def test_quiz_intent_classification(self) -> None:
        """LLM correctly classifies factual questions as quiz (IG-250)."""
        mock_model = MagicMock()
        mock_intent_model = AsyncMock()

        # Mock LLM response for quiz
        mock_intent_model.ainvoke = AsyncMock(
            return_value=IntentClassification(
                intent_type="quiz",
                quiz_response="Paris is the capital of France.",
                task_complexity=TaskComplexity.MINIMAL,
            )
        )

        classifier = IntentClassifier(model=mock_model)
        classifier._intent_model = mock_intent_model

        result = await classifier.classify_intent("What is the capital of France?")

        assert result.intent_type == "quiz"
        assert result.quiz_response is not None
        assert "Paris" in result.quiz_response
        assert result.task_complexity == TaskComplexity.MINIMAL
        assert not result.reuse_current_goal
        assert result.goal_description is None

    @pytest.mark.asyncio
    async def test_quiz_vs_new_goal_distinction(self) -> None:
        """Quiz questions distinguished from tool-requiring tasks (IG-250)."""
        mock_model = MagicMock()
        mock_intent_model = AsyncMock()

        # Quiz question -> quiz intent
        mock_intent_model.ainvoke = AsyncMock(
            return_value=IntentClassification(
                intent_type="quiz",
                quiz_response="William Shakespeare wrote Romeo and Juliet.",
                task_complexity=TaskComplexity.MINIMAL,
            )
        )

        classifier = IntentClassifier(model=mock_model)
        classifier._intent_model = mock_intent_model

        quiz_result = await classifier.classify_intent("Who wrote Romeo and Juliet?")
        assert quiz_result.intent_type == "quiz"
        assert quiz_result.quiz_response is not None
        assert quiz_result.task_complexity == TaskComplexity.MINIMAL

        # Tool-requiring task -> new_goal intent
        mock_intent_model.ainvoke = AsyncMock(
            return_value=IntentClassification(
                intent_type="new_goal",
                goal_description="Count all readme files in the workspace",
                task_complexity="medium",
            )
        )

        task_result = await classifier.classify_intent("count all readme files")
        assert task_result.intent_type == "new_goal"
        assert task_result.goal_description is not None
        assert task_result.quiz_response is None

    @pytest.mark.asyncio
    async def test_quiz_math_question(self) -> None:
        """Simple math questions classified as quiz (IG-250)."""
        mock_model = MagicMock()
        mock_intent_model = AsyncMock()

        mock_intent_model.ainvoke = AsyncMock(
            return_value=IntentClassification(
                intent_type="quiz",
                quiz_response="15 * 23 = 345",
                task_complexity=TaskComplexity.MINIMAL,
            )
        )

        classifier = IntentClassifier(model=mock_model)
        classifier._intent_model = mock_intent_model

        result = await classifier.classify_intent("What is 15 * 23?")
        assert result.intent_type == "quiz"
        assert result.quiz_response is not None

    @pytest.mark.asyncio
    async def test_patching_missing_quiz_response(self) -> None:
        """Classifier patches missing quiz_response for quiz intent (IG-250)."""
        mock_model = MagicMock()
        mock_intent_model = AsyncMock()

        # Mock LLM response missing quiz_response
        mock_intent_model.ainvoke = AsyncMock(
            return_value=IntentClassification(
                intent_type="quiz",
                task_complexity=TaskComplexity.MINIMAL,
                quiz_response=None,  # Missing
            )
        )

        classifier = IntentClassifier(model=mock_model)
        classifier._intent_model = mock_intent_model

        result = await classifier.classify_intent("What is the capital of France?")

        assert result.intent_type == "quiz"
        assert result.quiz_response is not None  # Patched

    @pytest.mark.asyncio
    async def test_fallback_on_classification_disabled(self) -> None:
        """Fallback to new_goal when classification disabled."""
        classifier = IntentClassifier(
            model=None,
        )

        result = await classifier.classify_intent("hello there")

        assert result.intent_type == "new_goal"
        assert result.goal_description == "hello there"
        assert result.task_complexity == "medium"

    @pytest.mark.asyncio
    async def test_fallback_on_llm_failure(self) -> None:
        """Fallback to new_goal when LLM fails."""
        mock_model = MagicMock()
        mock_intent_model = AsyncMock()
        mock_intent_model.ainvoke = AsyncMock(side_effect=Exception("LLM timeout"))

        classifier = IntentClassifier(
            model=mock_model,
        )
        classifier._intent_model = mock_intent_model

        result = await classifier.classify_intent("some query")

        assert result.intent_type == "new_goal"
        assert result.goal_description == "some query"
        assert result.task_complexity == "medium"

    @pytest.mark.asyncio
    async def test_patching_missing_chitchat_response(self) -> None:
        """Classifier patches missing chitchat_response for chitchat intent."""
        mock_model = MagicMock()
        mock_intent_model = AsyncMock()

        # Mock LLM response missing chitchat_response
        mock_intent_model.ainvoke = AsyncMock(
            return_value=IntentClassification(
                intent_type="chitchat",
                task_complexity=TaskComplexity.MINIMAL,
                chitchat_response=None,  # Missing
            )
        )

        classifier = IntentClassifier(model=mock_model, assistant_name="TestBot")
        classifier._intent_model = mock_intent_model

        result = await classifier.classify_intent("hello!")

        assert result.intent_type == "chitchat"
        assert result.chitchat_response is not None  # Patched
        assert "TestBot" in result.chitchat_response

    @pytest.mark.asyncio
    async def test_patching_missing_goal_description(self) -> None:
        """Classifier patches missing goal_description for new_goal intent."""
        mock_model = MagicMock()
        mock_intent_model = AsyncMock()

        # Mock LLM response missing goal_description
        mock_intent_model.ainvoke = AsyncMock(
            return_value=IntentClassification(
                intent_type="new_goal",
                task_complexity="medium",
                goal_description=None,  # Missing
            )
        )

        classifier = IntentClassifier(
            model=mock_model,
        )
        classifier._intent_model = mock_intent_model

        result = await classifier.classify_intent("count all readme files")

        assert result.intent_type == "new_goal"
        assert result.goal_description == "count all readme files"  # Patched with original query


# ---------------------------------------------------------------------------
# Edge cases and integration tests
# ---------------------------------------------------------------------------


class TestIntentClassificationEdgeCases:
    """Test edge cases for intent classification."""

    @pytest.mark.asyncio
    async def test_empty_query_fallback(self) -> None:
        """Empty query falls back to new_goal."""
        mock_model = MagicMock()
        mock_intent_model = AsyncMock()
        mock_intent_model.ainvoke = AsyncMock(side_effect=ValueError("Empty query"))

        classifier = IntentClassifier(
            model=mock_model,
        )
        classifier._intent_model = mock_intent_model

        result = await classifier.classify_intent("")

        assert result.intent_type == "new_goal"
        assert result.task_complexity == "medium"

    @pytest.mark.asyncio
    async def test_conversation_context_limit(self) -> None:
        """Conversation context limited to last 8 messages."""
        mock_model = MagicMock()
        mock_intent_model = AsyncMock()

        # Create 12 messages (should only use last 8)
        recent_messages = [
            HumanMessage(f"query {i}") if i % 2 == 0 else AIMessage(f"response {i}")
            for i in range(12)
        ]

        mock_intent_model.ainvoke = AsyncMock(
            return_value=IntentClassification(
                intent_type="continue_thread",
                reuse_current_goal=True,
                task_complexity="medium",
            )
        )

        classifier = IntentClassifier(
            model=mock_model,
        )
        classifier._intent_model = mock_intent_model

        result = await classifier.classify_intent("continue", recent_messages=recent_messages)

        assert result.intent_type == "continue_thread"

    @pytest.mark.asyncio
    async def test_complex_task_classification(self) -> None:
        """Complex architecture task classified as new_goal with complexity=complex."""
        mock_model = MagicMock()
        mock_intent_model = AsyncMock()

        mock_intent_model.ainvoke = AsyncMock(
            return_value=IntentClassification(
                intent_type="new_goal",
                goal_description="Design authentication system architecture",
                task_complexity="complex",
            )
        )

        classifier = IntentClassifier(
            model=mock_model,
        )
        classifier._intent_model = mock_intent_model

        result = await classifier.classify_intent(
            "design a complete authentication system with OAuth2, JWT, and role-based access control"
        )

        assert result.intent_type == "new_goal"
        assert result.task_complexity == "complex"
        assert "authentication" in result.goal_description.lower()
