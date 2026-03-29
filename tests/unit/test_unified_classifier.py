"""Tests for unified LLM-based routing classification system (RFC-0016)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from soothe.core.unified_classifier import (
    RoutingResult,
    UnifiedClassification,
    UnifiedClassifier,
    _looks_chinese,
)

# ---------------------------------------------------------------------------
# Pydantic model tests
# ---------------------------------------------------------------------------


class TestUnifiedClassification:
    """Test UnifiedClassification model."""

    def test_model_creation(self) -> None:
        classification = UnifiedClassification(task_complexity="medium", reasoning="Test reasoning")

        assert classification.task_complexity == "medium"
        assert classification.reasoning == "Test reasoning"

    def test_model_defaults(self) -> None:
        classification = UnifiedClassification(task_complexity="chitchat")

        assert classification.reasoning is None
        assert classification.chitchat_response is None

    def test_chitchat_response_field(self) -> None:
        classification = UnifiedClassification(
            task_complexity="chitchat",
            chitchat_response="Hello! How can I help you today?",
        )

        assert classification.chitchat_response == "Hello! How can I help you today?"

    def test_from_routing_chitchat(self) -> None:
        """Creating from routing result (chitchat) produces correct result."""
        routing = RoutingResult(task_complexity="chitchat", chitchat_response="Hi!")
        merged = UnifiedClassification.from_routing(routing)

        assert merged.task_complexity == "chitchat"
        assert merged.chitchat_response == "Hi!"

    def test_from_routing_medium(self) -> None:
        """Creating from routing result (medium) produces correct result."""
        routing = RoutingResult(task_complexity="medium")
        merged = UnifiedClassification.from_routing(routing)

        assert merged.task_complexity == "medium"
        assert merged.chitchat_response is None


class TestRoutingResult:
    """Test RoutingResult model."""

    def test_defaults(self) -> None:
        r = RoutingResult(task_complexity="medium")
        assert r.chitchat_response is None

    def test_with_response(self) -> None:
        r = RoutingResult(task_complexity="chitchat", chitchat_response="Hello!")
        assert r.chitchat_response == "Hello!"


# ---------------------------------------------------------------------------
# Classifier init tests
# ---------------------------------------------------------------------------


class TestUnifiedClassifier:
    """Test UnifiedClassifier class."""

    def test_init_with_model(self) -> None:
        mock_model = MagicMock()
        mock_model.with_structured_output = MagicMock(return_value=mock_model)

        classifier = UnifiedClassifier(fast_model=mock_model, classification_mode="llm")

        assert classifier._fast_model == mock_model
        assert classifier._mode == "llm"
        assert classifier._routing_model is not None

    def test_init_without_model(self) -> None:
        classifier = UnifiedClassifier(fast_model=None, classification_mode="disabled")

        assert classifier._fast_model is None
        assert classifier._mode == "disabled"
        assert classifier._routing_model is None

    def test_init_default_mode(self) -> None:
        mock_model = MagicMock()
        mock_model.with_structured_output = MagicMock(return_value=mock_model)

        classifier = UnifiedClassifier(fast_model=mock_model)

        assert classifier._mode == "llm"


# ---------------------------------------------------------------------------
# Classify routing tests
# ---------------------------------------------------------------------------


class TestClassifyRouting:
    """Test tier-1 routing classification."""

    @pytest.mark.asyncio
    async def test_routing_chitchat(self) -> None:
        mock_model = MagicMock()
        mock_routing = MagicMock()
        mock_routing.ainvoke = AsyncMock(
            return_value=RoutingResult(task_complexity="chitchat", chitchat_response="Hi!")
        )
        mock_model.with_structured_output = MagicMock(return_value=mock_routing)

        classifier = UnifiedClassifier(fast_model=mock_model, classification_mode="llm")
        result = await classifier.classify_routing("hello")

        assert result.task_complexity == "chitchat"
        assert result.chitchat_response == "Hi!"

    @pytest.mark.asyncio
    async def test_routing_medium(self) -> None:
        mock_model = MagicMock()
        mock_routing = MagicMock()
        mock_routing.ainvoke = AsyncMock(return_value=RoutingResult(task_complexity="medium"))
        mock_model.with_structured_output = MagicMock(return_value=mock_routing)

        classifier = UnifiedClassifier(fast_model=mock_model, classification_mode="llm")
        result = await classifier.classify_routing("search for Python docs")

        assert result.task_complexity == "medium"
        assert result.chitchat_response is None

    @pytest.mark.asyncio
    async def test_routing_disabled_mode(self) -> None:
        classifier = UnifiedClassifier(fast_model=None, classification_mode="disabled")
        result = await classifier.classify_routing("hello")

        assert result.task_complexity == "medium"  # Safe default

    @pytest.mark.asyncio
    async def test_routing_llm_failure_returns_defaults(self) -> None:
        mock_model = MagicMock()
        mock_routing = MagicMock()
        mock_routing.ainvoke = AsyncMock(side_effect=[Exception("LLM error"), Exception("LLM error")])
        mock_model.with_structured_output = MagicMock(return_value=mock_routing)

        classifier = UnifiedClassifier(fast_model=mock_model, classification_mode="llm")
        result = await classifier.classify_routing("test query")

        assert result.task_complexity == "medium"  # Fallback
        assert mock_routing.ainvoke.await_count == 2

    @pytest.mark.asyncio
    async def test_routing_retries_then_succeeds(self) -> None:
        mock_model = MagicMock()
        mock_routing = MagicMock()
        mock_routing.ainvoke = AsyncMock(
            side_effect=[
                Exception("OutputParserException"),
                RoutingResult(
                    task_complexity="chitchat",
                    chitchat_response="I'm doing well, thanks for asking!",
                ),
            ]
        )
        mock_model.with_structured_output = MagicMock(return_value=mock_routing)

        classifier = UnifiedClassifier(fast_model=mock_model, classification_mode="llm")
        result = await classifier.classify_routing("how are you")

        assert result.task_complexity == "chitchat"
        assert result.chitchat_response is not None
        assert mock_routing.ainvoke.await_count == 2

    @pytest.mark.asyncio
    async def test_how_are_you_chitchat_when_llm_output_is_valid(self) -> None:
        mock_model = MagicMock()
        mock_routing = MagicMock()
        mock_routing.ainvoke = AsyncMock(
            return_value=RoutingResult(
                task_complexity="chitchat",
                chitchat_response="I'm doing well, thank you! How can I help?",
            )
        )
        mock_model.with_structured_output = MagicMock(return_value=mock_routing)

        classifier = UnifiedClassifier(fast_model=mock_model, classification_mode="llm")
        result = await classifier.classify_routing("how are you")

        assert result.task_complexity == "chitchat"
        assert result.chitchat_response is not None


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    """Test edge cases and special scenarios."""

    @pytest.mark.asyncio
    async def test_multilingual_routing(self) -> None:
        """Routing handles non-English queries."""
        mock_model = MagicMock()
        mock_routing = MagicMock()
        mock_routing.ainvoke = AsyncMock(return_value=RoutingResult(task_complexity="medium"))
        mock_model.with_structured_output = MagicMock(return_value=mock_routing)

        classifier = UnifiedClassifier(fast_model=mock_model, classification_mode="llm")
        routing = await classifier.classify_routing("只做计划,不要执行")

        assert routing.task_complexity == "medium"

    @pytest.mark.asyncio
    async def test_very_long_query(self) -> None:
        """Routing handles very long queries."""
        mock_model = MagicMock()
        mock_routing = MagicMock()
        mock_routing.ainvoke = AsyncMock(return_value=RoutingResult(task_complexity="complex"))
        mock_model.with_structured_output = MagicMock(return_value=mock_routing)

        classifier = UnifiedClassifier(fast_model=mock_model, classification_mode="llm")
        long_query = "Analyze " * 100  # 700+ characters
        routing = await classifier.classify_routing(long_query)

        assert routing.task_complexity == "complex"


# ---------------------------------------------------------------------------
# Chitchat response guarantee
# ---------------------------------------------------------------------------


class TestChitchatResponseGuarantee:
    """Test that chitchat responses are always provided."""

    @pytest.mark.asyncio
    async def test_chitchat_response_always_present(self) -> None:
        """When LLM omits chitchat_response for chitchat, patch it."""
        mock_model = MagicMock()
        mock_routing = MagicMock()
        # LLM returns chitchat complexity but forgets response
        mock_routing.ainvoke = AsyncMock(return_value=RoutingResult(task_complexity="chitchat", chitchat_response=None))
        mock_model.with_structured_output = MagicMock(return_value=mock_routing)

        classifier = UnifiedClassifier(fast_model=mock_model, classification_mode="llm")
        result = await classifier.classify_routing("hi there")

        assert result.task_complexity == "chitchat"
        assert result.chitchat_response is not None
        assert "Soothe" in result.chitchat_response

    @pytest.mark.asyncio
    async def test_chinese_chitchat_gets_chinese_response(self) -> None:
        """Chinese chitchat queries get Chinese responses when LLM omits."""
        mock_model = MagicMock()
        mock_routing = MagicMock()
        mock_routing.ainvoke = AsyncMock(return_value=RoutingResult(task_complexity="chitchat", chitchat_response=None))
        mock_model.with_structured_output = MagicMock(return_value=mock_routing)

        classifier = UnifiedClassifier(fast_model=mock_model, classification_mode="llm")
        result = await classifier.classify_routing("你好")

        assert result.task_complexity == "chitchat"
        assert result.chitchat_response is not None
        # Should contain Chinese characters
        assert any("\u4e00" <= ch <= "\u9fff" for ch in result.chitchat_response)


# ---------------------------------------------------------------------------
# Helper function tests
# ---------------------------------------------------------------------------


class TestLooksChinese:
    """Test _looks_chinese helper."""

    def test_chinese_text(self) -> None:
        assert _looks_chinese("你好世界") is True

    def test_english_text(self) -> None:
        assert _looks_chinese("hello world") is False

    def test_mixed_text(self) -> None:
        assert _looks_chinese("hello 你好") is True

    def test_empty_text(self) -> None:
        assert _looks_chinese("") is False


# ---------------------------------------------------------------------------
# Default classification tests
# ---------------------------------------------------------------------------


class TestDefaultClassification:
    """Test default classification behavior."""

    def test_default_classification(self) -> None:
        classifier = UnifiedClassifier(fast_model=None, classification_mode="disabled")
        default = classifier._default_classification("test reason")

        assert default.task_complexity == "medium"
        assert default.reasoning == "test reason"
