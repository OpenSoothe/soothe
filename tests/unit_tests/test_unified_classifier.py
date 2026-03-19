"""Tests for unified LLM-based classification system (RFC-0012)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from soothe.core.unified_classifier import UnifiedClassification, UnifiedClassifier


class TestUnifiedClassification:
    """Test UnifiedClassification model."""

    def test_model_creation(self) -> None:
        """Test creating a UnifiedClassification instance."""
        classification = UnifiedClassification(task_complexity="medium", is_plan_only=True, reasoning="Test reasoning")

        assert classification.task_complexity == "medium"
        assert classification.is_plan_only is True
        assert classification.reasoning == "Test reasoning"

    def test_model_defaults(self) -> None:
        """Test default values for UnifiedClassification."""
        classification = UnifiedClassification(task_complexity="chitchat", is_plan_only=False)

        assert classification.reasoning is None


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
        classifier = UnifiedClassifier(fast_model=None, classification_mode="fallback")

        assert classifier._fast_model is None
        assert classifier._mode == "fallback"
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
    async def test_classify_fallback_mode(self) -> None:
        """Test classification in fallback mode (token-count only)."""
        classifier = UnifiedClassifier(fast_model=None, classification_mode="fallback", use_tiktoken=False)

        # Short query -> chitchat
        result = await classifier.classify("hello world")
        assert result.task_complexity == "chitchat"
        assert result.is_plan_only is False

        # Medium query -> medium (needs to be 30+ tokens)
        # Use query that starts with "create a plan" to trigger plan-only heuristic
        medium_query = (
            "create a plan for implementing user authentication with OAuth2 and JWT tokens "
            "in our microservices architecture including security considerations and deployment strategies"
        )
        result = await classifier.classify(medium_query)
        assert result.task_complexity == "medium"
        assert result.is_plan_only is True  # Starts with "create a plan"

        # Long query -> complex (simulate with repeated text)
        long_query = "architect a comprehensive system design " * 20
        result = await classifier.classify(long_query)
        assert result.task_complexity == "complex"

    @pytest.mark.asyncio
    async def test_classify_llm_mode_success(self) -> None:
        """Test successful LLM classification."""
        mock_model = MagicMock()
        mock_structured = AsyncMock()
        mock_structured.ainvoke = AsyncMock(
            return_value=UnifiedClassification(task_complexity="complex", is_plan_only=False, reasoning="LLM analysis")
        )
        mock_model.with_structured_output = MagicMock(return_value=mock_structured)

        classifier = UnifiedClassifier(fast_model=mock_model, classification_mode="llm")

        result = await classifier.classify("implement complex architecture")

        assert result.task_complexity == "complex"
        assert result.is_plan_only is False
        assert result.reasoning == "LLM analysis"

    @pytest.mark.asyncio
    async def test_classify_llm_mode_fallback_on_error(self) -> None:
        """Test LLM mode falls back on error."""
        mock_model = MagicMock()
        mock_structured = AsyncMock()
        mock_structured.ainvoke = AsyncMock(side_effect=Exception("LLM error"))
        mock_model.with_structured_output = MagicMock(return_value=mock_structured)

        classifier = UnifiedClassifier(fast_model=mock_model, classification_mode="llm", use_tiktoken=False)

        result = await classifier.classify("test query")

        # Should use fallback (token-count)
        assert result.task_complexity == "chitchat"
        assert "fallback" in result.reasoning.lower()

    @pytest.mark.asyncio
    async def test_classify_no_model_fallback(self) -> None:
        """Test that missing model triggers fallback."""
        classifier = UnifiedClassifier(
            fast_model=None,
            classification_mode="llm",  # Request LLM but no model provided
            use_tiktoken=False,
        )

        result = await classifier.classify("test query")

        # Should use fallback
        assert result.task_complexity == "chitchat"
        assert "fallback" in result.reasoning.lower()


class TestTokenCountFallback:
    """Test token-count fallback logic."""

    @pytest.mark.asyncio
    async def test_task_complexity_thresholds(self) -> None:
        """Test task complexity thresholds (30, 160 tokens)."""
        classifier = UnifiedClassifier(fast_model=None, classification_mode="fallback", use_tiktoken=False)

        # < 30 tokens -> chitchat
        short = "a" * 100  # 25 tokens
        result = await classifier.classify(short)
        assert result.task_complexity == "chitchat"

        # 30-159 tokens -> medium
        medium = "a" * 140  # 35 tokens
        result = await classifier.classify(medium)
        assert result.task_complexity == "medium"

        # >= 160 tokens -> complex
        long = "a" * 680  # 170 tokens
        result = await classifier.classify(long)
        assert result.task_complexity == "complex"

    @pytest.mark.asyncio
    async def test_plan_only_detection(self) -> None:
        """Test plan-only intent detection."""
        classifier = UnifiedClassifier(fast_model=None, classification_mode="fallback")

        # Should detect plan-only
        assert (await classifier.classify("create a plan for authentication")).is_plan_only is True
        assert (await classifier.classify("make a plan")).is_plan_only is True
        assert (await classifier.classify("plan only please")).is_plan_only is True
        assert (await classifier.classify("only plan, don't execute")).is_plan_only is True

        # Should not detect plan-only
        assert (await classifier.classify("implement authentication")).is_plan_only is False
        assert (await classifier.classify("create a user authentication system")).is_plan_only is False


class TestEdgeCases:
    """Test edge cases and special scenarios."""

    @pytest.mark.asyncio
    async def test_empty_query(self) -> None:
        """Test classification of empty query."""
        classifier = UnifiedClassifier(fast_model=None, classification_mode="fallback")

        result = await classifier.classify("")
        assert result.task_complexity == "chitchat"  # 0 tokens
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
        classifier = UnifiedClassifier(fast_model=None, classification_mode="fallback", use_tiktoken=False)

        # Very long query (> 200 tokens)
        long_query = "implement a comprehensive system " * 50
        result = await classifier.classify(long_query)

        assert result.task_complexity == "complex"

    @pytest.mark.asyncio
    async def test_whitespace_handling(self) -> None:
        """Test that whitespace is handled correctly."""
        classifier = UnifiedClassifier(fast_model=None, classification_mode="fallback")

        # Query with extra whitespace
        result = await classifier.classify("  create a plan  ")
        assert result.is_plan_only is True


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
