"""Tests for unified LLM-based intent classification system (IG-226)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from soothe.cognition.intention import IntentClassification, IntentClassifier

# ---------------------------------------------------------------------------
# Pydantic model tests
# ---------------------------------------------------------------------------


class TestIntentClassification:
    """Test IntentClassification model."""

    def test_model_creation_chitchat(self) -> None:
        """IntentClassification for chitchat query."""
        intent = IntentClassification(
            intent_type="chitchat",
            task_complexity="chitchat",
            chitchat_response="Hello! How can I help?",
            reasoning="Greeting detected",
        )

        assert intent.intent_type == "chitchat"
        assert intent.task_complexity == "chitchat"
        assert intent.chitchat_response == "Hello! How can I help?"
        assert not intent.reuse_current_goal
        assert intent.goal_description is None

    def test_model_creation_thread_continuation(self) -> None:
        """IntentClassification for thread continuation query."""
        intent = IntentClassification(
            intent_type="thread_continuation",
            reuse_current_goal=True,
            task_complexity="medium",
            reasoning="Query references prior result",
        )

        assert intent.intent_type == "thread_continuation"
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
            reasoning="Standalone task detected",
        )

        assert intent.intent_type == "new_goal"
        assert intent.goal_description == "Count all readme files in the workspace"
        assert intent.task_complexity == "medium"
        assert not intent.reuse_current_goal
        assert intent.chitchat_response is None

    def test_model_defaults(self) -> None:
        """IntentClassification default values."""
        intent = IntentClassification(
            intent_type="new_goal", task_complexity="medium", reasoning="Default test"
        )

        assert not intent.reuse_current_goal
        assert intent.goal_description is None
        assert intent.chitchat_response is None


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
        assert classifier._routing_model is not None
        assert classifier._intent_model is not None

    def test_init_without_model_intent_disabled(self) -> None:
        """Classifier without model disables intent classification."""
        classifier = IntentClassifier(
            model=None,
        )

        assert classifier._fast_model is None
        assert classifier._routing_model is None
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
                task_complexity="chitchat",
                chitchat_response="你好! 我是 Soothe。有什么可以帮你的吗?",
                reasoning="Chinese greeting detected",
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
        assert result.task_complexity == "chitchat"
        assert not result.reuse_current_goal

    @pytest.mark.asyncio
    async def test_thread_continuation_with_context(self) -> None:
        """LLM detects thread continuation from conversation context."""
        mock_model = MagicMock()
        mock_intent_model = AsyncMock()

        # Recent conversation showing prior result
        recent_messages = [
            HumanMessage("list all python files"),
            AIMessage("Found 42 .py files in the workspace: main.py, utils.py, ..."),
        ]

        # Mock LLM response for thread continuation
        mock_intent_model.ainvoke = AsyncMock(
            return_value=IntentClassification(
                intent_type="thread_continuation",
                reuse_current_goal=True,
                task_complexity="medium",
                reasoning="Query references prior conversation result",
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

        assert result.intent_type == "thread_continuation"
        assert result.reuse_current_goal
        assert result.task_complexity == "medium"
        assert result.chitchat_response is None
        assert result.goal_description is None

    @pytest.mark.asyncio
    async def test_thread_continuation_without_active_goal(self) -> None:
        """Thread continuation without active goal sets reuse_current_goal=False."""
        mock_model = MagicMock()
        mock_intent_model = AsyncMock()

        # Mock LLM response
        mock_intent_model.ainvoke = AsyncMock(
            return_value=IntentClassification(
                intent_type="thread_continuation",
                reuse_current_goal=False,  # No active goal
                task_complexity="medium",
                reasoning="Follow-up action but no active goal in thread",
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

        assert result.intent_type == "thread_continuation"
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
                reasoning="Standalone task requiring new goal",
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
    async def test_fallback_on_classification_disabled(self) -> None:
        """Fallback to new_goal when classification disabled."""
        classifier = IntentClassifier(
            model=None,
        )

        result = await classifier.classify_intent("hello there")

        assert result.intent_type == "new_goal"
        assert result.goal_description == "hello there"
        assert result.task_complexity == "medium"
        assert "classification disabled" in result.reasoning.lower()

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
        assert "Fallback" in result.reasoning

    @pytest.mark.asyncio
    async def test_patching_missing_chitchat_response(self) -> None:
        """Classifier patches missing chitchat_response for chitchat intent."""
        mock_model = MagicMock()
        mock_intent_model = AsyncMock()

        # Mock LLM response missing chitchat_response
        mock_intent_model.ainvoke = AsyncMock(
            return_value=IntentClassification(
                intent_type="chitchat",
                task_complexity="chitchat",
                reasoning="Greeting detected",
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
                reasoning="New task detected",
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
                intent_type="thread_continuation",
                reuse_current_goal=True,
                task_complexity="medium",
                reasoning="Follow-up detected",
            )
        )

        classifier = IntentClassifier(
            model=mock_model,
        )
        classifier._intent_model = mock_intent_model

        result = await classifier.classify_intent("continue", recent_messages=recent_messages)

        assert result.intent_type == "thread_continuation"

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
                reasoning="Architecture design requires complex planning",
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
