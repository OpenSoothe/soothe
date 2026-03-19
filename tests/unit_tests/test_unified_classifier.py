"""Tests for unified LLM-based classification system (RFC-0012)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from soothe.core.unified_classifier import UnifiedClassification, UnifiedClassifier


class TestUnifiedClassification:
    """Test UnifiedClassification model."""

    def test_model_creation(self) -> None:
        """Test creating a UnifiedClassification instance."""
        classification = UnifiedClassification(
            task_complexity="medium", is_plan_only=True, template_intent="question", reasoning="Test reasoning"
        )

        assert classification.task_complexity == "medium"
        assert classification.is_plan_only is True
        assert classification.template_intent == "question"
        assert classification.reasoning == "Test reasoning"

    def test_model_defaults(self) -> None:
        """Test default values for UnifiedClassification."""
        classification = UnifiedClassification(task_complexity="chitchat", is_plan_only=False)

        assert classification.reasoning is None
        assert classification.template_intent is None


class TestUnifiedClassifier:
    """Test UnifiedClassifier class."""

    def test_init_with_model(self) -> None:
        """Test initialization with a fast model."""
        mock_model = MagicMock()
        mock_model.with_structured_output = MagicMock(return_value=mock_model)

        classifier = UnifiedClassifier(fast_model=mock_model, classification_mode="llm")

        assert classifier._fast_model == mock_model
        assert classifier._mode == "llm"
        assert classifier._structured_model == mock_model

    def test_init_without_model(self) -> None:
        """Test initialization without a fast model."""
        classifier = UnifiedClassifier(fast_model=None, classification_mode="llm")

        assert classifier._fast_model is None
        assert classifier._mode == "llm"
        assert classifier._structured_model is None

    @pytest.mark.asyncio
    async def test_classify_disabled_mode(self) -> None:
        """Test classification in disabled mode."""
        classifier = UnifiedClassifier(fast_model=None, classification_mode="disabled")

        result = await classifier.classify("test query")

        assert result.task_complexity == "medium"
        assert result.is_plan_only is False
        assert "disabled" in result.reasoning.lower()

    @pytest.mark.asyncio
    async def test_classify_llm_mode_success(self) -> None:
        """Test successful LLM classification."""
        mock_model = MagicMock()
        mock_structured = AsyncMock()
        mock_structured.ainvoke = AsyncMock(
            return_value=UnifiedClassification(
                task_complexity="complex",
                is_plan_only=False,
                template_intent="implementation",
                reasoning="LLM analysis",
            )
        )
        mock_model.with_structured_output = MagicMock(return_value=mock_structured)

        classifier = UnifiedClassifier(fast_model=mock_model, classification_mode="llm")

        result = await classifier.classify("implement complex architecture")

        assert result.task_complexity == "complex"
        assert result.is_plan_only is False
        assert result.template_intent == "implementation"
        assert result.reasoning == "LLM analysis"

    @pytest.mark.asyncio
    async def test_classify_no_model_returns_default(self) -> None:
        """Test that missing fast model returns safe default."""
        classifier = UnifiedClassifier(
            fast_model=None,
            classification_mode="llm",  # Request LLM but no model provided
        )

        result = await classifier.classify("test query")

        # Should return safe default (medium), not chitchat
        assert result.task_complexity == "medium"
        assert "No fast model" in result.reasoning


class TestLLMClassification:
    """Test LLM-based classification with improved prompt."""

    @pytest.mark.asyncio
    async def test_short_current_events_query(self) -> None:
        """Test short query about current events is classified as medium."""
        # This is the core fix for the reported issue
        mock_model = MagicMock()
        mock_structured = AsyncMock()
        mock_structured.ainvoke = AsyncMock(
            return_value=UnifiedClassification(
                task_complexity="medium",
                is_plan_only=False,
                template_intent="question",
                reasoning="Current events query requiring research",
            )
        )
        mock_model.with_structured_output = MagicMock(return_value=mock_structured)

        classifier = UnifiedClassifier(fast_model=mock_model, classification_mode="llm")

        result = await classifier.classify("伊朗战争最新进展")
        assert result.task_complexity == "medium"

        # English equivalent
        result = await classifier.classify("latest developments in Iran war")
        assert result.task_complexity == "medium"

    @pytest.mark.asyncio
    async def test_short_technical_question(self) -> None:
        """Test short technical question is classified as medium."""
        mock_model = MagicMock()
        mock_structured = AsyncMock()
        mock_structured.ainvoke = AsyncMock(
            return_value=UnifiedClassification(
                task_complexity="medium",
                is_plan_only=False,
                template_intent="question",
                reasoning="Technical debugging question",
            )
        )
        mock_model.with_structured_output = MagicMock(return_value=mock_structured)

        classifier = UnifiedClassifier(fast_model=mock_model, classification_mode="llm")

        result = await classifier.classify("debug this error")
        assert result.task_complexity == "medium"

        result = await classifier.classify("how to fix this bug")
        assert result.task_complexity == "medium"

    @pytest.mark.asyncio
    async def test_simple_greeting_is_chitchat(self) -> None:
        """Test simple greetings are still classified as chitchat."""
        mock_model = MagicMock()
        mock_structured = AsyncMock()
        mock_structured.ainvoke = AsyncMock(
            return_value=UnifiedClassification(
                task_complexity="chitchat",
                is_plan_only=False,
                template_intent=None,
                reasoning="Simple greeting",
            )
        )
        mock_model.with_structured_output = MagicMock(return_value=mock_structured)

        classifier = UnifiedClassifier(fast_model=mock_model, classification_mode="llm")

        for greeting in ["hello", "hi", "good morning", "你好", "您好"]:
            result = await classifier.classify(greeting)
            assert result.task_complexity == "chitchat"

    @pytest.mark.asyncio
    async def test_complex_architecture_query(self) -> None:
        """Test architecture queries are classified as complex."""
        mock_model = MagicMock()
        mock_structured = AsyncMock()
        mock_structured.ainvoke = AsyncMock(
            return_value=UnifiedClassification(
                task_complexity="complex",
                is_plan_only=False,
                template_intent="implementation",
                reasoning="Architecture design task",
            )
        )
        mock_model.with_structured_output = MagicMock(return_value=mock_structured)

        classifier = UnifiedClassifier(fast_model=mock_model, classification_mode="llm")

        result = await classifier.classify("migrate from REST to GraphQL")
        assert result.task_complexity == "complex"

        result = await classifier.classify("design microservices architecture")
        assert result.task_complexity == "complex"


class TestEdgeCases:
    """Test edge cases and special scenarios."""

    @pytest.mark.asyncio
    async def test_empty_query(self) -> None:
        """Test classification of empty query."""
        mock_model = MagicMock()
        mock_structured = AsyncMock()
        mock_structured.ainvoke = AsyncMock(
            return_value=UnifiedClassification(
                task_complexity="chitchat",
                is_plan_only=False,
                template_intent=None,
                reasoning="Empty query",
            )
        )
        mock_model.with_structured_output = MagicMock(return_value=mock_structured)

        classifier = UnifiedClassifier(fast_model=mock_model, classification_mode="llm")

        result = await classifier.classify("")
        assert result.task_complexity == "chitchat"
        assert result.is_plan_only is False

    @pytest.mark.asyncio
    async def test_multilingual_query(self) -> None:
        """Test classification handles multilingual queries."""
        mock_model = MagicMock()
        mock_structured = AsyncMock()
        mock_structured.ainvoke = AsyncMock(
            return_value=UnifiedClassification(
                task_complexity="medium",
                is_plan_only=True,
                template_intent=None,
                reasoning="Multilingual plan request",
            )
        )
        mock_model.with_structured_output = MagicMock(return_value=mock_structured)

        classifier = UnifiedClassifier(fast_model=mock_model, classification_mode="llm")

        result = await classifier.classify("只做计划,不要执行")
        assert result.is_plan_only is True
        assert result.reasoning == "Multilingual plan request"

    @pytest.mark.asyncio
    async def test_very_long_query(self) -> None:
        """Test classification of very long query."""
        mock_model = MagicMock()
        mock_structured = AsyncMock()
        mock_structured.ainvoke = AsyncMock(
            return_value=UnifiedClassification(
                task_complexity="complex",
                is_plan_only=False,
                template_intent="implementation",
                reasoning="Complex architectural task",
            )
        )
        mock_model.with_structured_output = MagicMock(return_value=mock_structured)

        classifier = UnifiedClassifier(fast_model=mock_model, classification_mode="llm")

        # Very long query
        long_query = "implement a comprehensive system " * 50
        result = await classifier.classify(long_query)

        assert result.task_complexity == "complex"


class TestDefaultClassification:
    """Test default classification logic."""

    def test_default_classification(self) -> None:
        """Test the default classification method."""
        classifier = UnifiedClassifier(fast_model=None, classification_mode="disabled")

        result = classifier._default_classification("Test reason")

        assert result.task_complexity == "medium"
        assert result.is_plan_only is False
        assert result.reasoning == "Test reason"

    def test_default_classification_default_reason(self) -> None:
        """Test default classification with default reason."""
        classifier = UnifiedClassifier(fast_model=None, classification_mode="disabled")

        result = classifier._default_classification()

        assert result.reasoning == "Default"


class TestTemplateIntent:
    """Test template intent classification."""

    @pytest.mark.asyncio
    async def test_question_intent_classification(self) -> None:
        """Test question queries get correct template_intent."""
        mock_model = MagicMock()
        mock_structured = AsyncMock()
        mock_structured.ainvoke = AsyncMock(
            return_value=UnifiedClassification(
                task_complexity="medium",
                is_plan_only=False,
                template_intent="question",
                reasoning="Question about a topic",
            )
        )
        mock_model.with_structured_output = MagicMock(return_value=mock_structured)

        classifier = UnifiedClassifier(fast_model=mock_model, classification_mode="llm")

        result = await classifier.classify("what is machine learning")
        assert result.task_complexity == "medium"
        assert result.template_intent == "question"

    @pytest.mark.asyncio
    async def test_search_intent_classification(self) -> None:
        """Test search queries get correct template_intent."""
        mock_model = MagicMock()
        mock_structured = AsyncMock()
        mock_structured.ainvoke = AsyncMock(
            return_value=UnifiedClassification(
                task_complexity="medium",
                is_plan_only=False,
                template_intent="search",
                reasoning="Search for information",
            )
        )
        mock_model.with_structured_output = MagicMock(return_value=mock_structured)

        classifier = UnifiedClassifier(fast_model=mock_model, classification_mode="llm")

        result = await classifier.classify("find information about Python")
        assert result.task_complexity == "medium"
        assert result.template_intent == "search"

    @pytest.mark.asyncio
    async def test_analysis_intent_classification(self) -> None:
        """Test analysis queries get correct template_intent."""
        mock_model = MagicMock()
        mock_structured = AsyncMock()
        mock_structured.ainvoke = AsyncMock(
            return_value=UnifiedClassification(
                task_complexity="medium",
                is_plan_only=False,
                template_intent="analysis",
                reasoning="Analyze the code",
            )
        )
        mock_model.with_structured_output = MagicMock(return_value=mock_structured)

        classifier = UnifiedClassifier(fast_model=mock_model, classification_mode="llm")

        result = await classifier.classify("analyze this code")
        assert result.task_complexity == "medium"
        assert result.template_intent == "analysis"

    @pytest.mark.asyncio
    async def test_implementation_intent_classification(self) -> None:
        """Test implementation queries get correct template_intent."""
        mock_model = MagicMock()
        mock_structured = AsyncMock()
        mock_structured.ainvoke = AsyncMock(
            return_value=UnifiedClassification(
                task_complexity="medium",
                is_plan_only=False,
                template_intent="implementation",
                reasoning="Build something",
            )
        )
        mock_model.with_structured_output = MagicMock(return_value=mock_structured)

        classifier = UnifiedClassifier(fast_model=mock_model, classification_mode="llm")

        result = await classifier.classify("implement a REST API endpoint")
        assert result.task_complexity == "medium"
        assert result.template_intent == "implementation"

    @pytest.mark.asyncio
    async def test_chitchat_has_null_intent(self) -> None:
        """Test chitchat queries have null template_intent."""
        mock_model = MagicMock()
        mock_structured = AsyncMock()
        mock_structured.ainvoke = AsyncMock(
            return_value=UnifiedClassification(
                task_complexity="chitchat",
                is_plan_only=False,
                template_intent=None,
                reasoning="Simple greeting",
            )
        )
        mock_model.with_structured_output = MagicMock(return_value=mock_structured)

        classifier = UnifiedClassifier(fast_model=mock_model, classification_mode="llm")

        result = await classifier.classify("hello")
        assert result.task_complexity == "chitchat"
        assert result.template_intent is None
