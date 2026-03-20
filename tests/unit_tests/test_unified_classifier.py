"""Tests for unified two-tier LLM-based classification system (RFC-0012)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from soothe.cognition import (
    EnrichmentResult,
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
        classification = UnifiedClassification(
            task_complexity="medium", is_plan_only=True, template_intent="question", reasoning="Test reasoning"
        )

        assert classification.task_complexity == "medium"
        assert classification.is_plan_only is True
        assert classification.template_intent == "question"
        assert classification.reasoning == "Test reasoning"

    def test_model_defaults(self) -> None:
        classification = UnifiedClassification(task_complexity="chitchat", is_plan_only=False)

        assert classification.reasoning is None
        assert classification.template_intent is None
        assert classification.chitchat_response is None

    def test_chitchat_response_field(self) -> None:
        classification = UnifiedClassification(
            task_complexity="chitchat",
            is_plan_only=False,
            chitchat_response="Hello! How can I help you today?",
        )

        assert classification.chitchat_response == "Hello! How can I help you today?"

    def test_from_tiers_chitchat(self) -> None:
        """Merging tier-1 only (chitchat) produces correct result."""
        routing = RoutingResult(task_complexity="chitchat", chitchat_response="Hi!")
        merged = UnifiedClassification.from_tiers(routing, enrichment=None)

        assert merged.task_complexity == "chitchat"
        assert merged.chitchat_response == "Hi!"
        assert merged.is_plan_only is False
        assert merged.template_intent is None

    def test_from_tiers_medium(self) -> None:
        """Merging tier-1 + tier-2 produces correct result."""
        routing = RoutingResult(task_complexity="medium")
        enrichment = EnrichmentResult(
            is_plan_only=True,
            template_intent="search",
            capability_domains=["research"],
            reasoning="needs web search",
        )
        merged = UnifiedClassification.from_tiers(routing, enrichment)

        assert merged.task_complexity == "medium"
        assert merged.is_plan_only is True
        assert merged.template_intent == "search"
        assert merged.capability_domains == ["research"]
        assert merged.reasoning == "needs web search"
        assert merged.chitchat_response is None


class TestRoutingResult:
    """Test RoutingResult model."""

    def test_defaults(self) -> None:
        r = RoutingResult(task_complexity="medium")
        assert r.chitchat_response is None

    def test_with_response(self) -> None:
        r = RoutingResult(task_complexity="chitchat", chitchat_response="Hello!")
        assert r.chitchat_response == "Hello!"


class TestEnrichmentResult:
    """Test EnrichmentResult model."""

    def test_defaults(self) -> None:
        e = EnrichmentResult()
        assert e.is_plan_only is False
        assert e.template_intent is None
        assert e.capability_domains == []
        assert e.reasoning is None


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
        assert classifier._enrichment_model is not None

    def test_init_without_model(self) -> None:
        classifier = UnifiedClassifier(fast_model=None, classification_mode="llm")

        assert classifier._fast_model is None
        assert classifier._mode == "llm"
        assert classifier._routing_model is None
        assert classifier._enrichment_model is None

    def test_assistant_name_passed_to_classifier(self) -> None:
        mock_model = MagicMock()
        mock_model.with_structured_output = MagicMock(return_value=mock_model)

        classifier = UnifiedClassifier(
            fast_model=mock_model,
            classification_mode="llm",
            assistant_name="TestBot",
        )
        assert classifier._assistant_name == "TestBot"

    def test_default_assistant_name(self) -> None:
        classifier = UnifiedClassifier(fast_model=None, classification_mode="disabled")
        assert classifier._assistant_name == "Soothe"


# ---------------------------------------------------------------------------
# Tier-1 routing tests
# ---------------------------------------------------------------------------


class TestClassifyRouting:
    """Test tier-1 fast routing classification."""

    @pytest.mark.asyncio
    async def test_routing_chitchat(self) -> None:
        mock_model = MagicMock()
        mock_routing = AsyncMock()
        mock_routing.ainvoke = AsyncMock(
            return_value=RoutingResult(
                task_complexity="chitchat",
                chitchat_response="Hello there!",
            )
        )
        mock_model.with_structured_output = MagicMock(return_value=mock_routing)

        classifier = UnifiedClassifier(fast_model=mock_model, classification_mode="llm")

        result = await classifier.classify_routing("hi")
        assert result.task_complexity == "chitchat"
        assert result.chitchat_response == "Hello there!"

    @pytest.mark.asyncio
    async def test_routing_medium(self) -> None:
        mock_model = MagicMock()
        mock_routing = AsyncMock()
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
        assert result.task_complexity == "medium"

    @pytest.mark.asyncio
    async def test_routing_no_model(self) -> None:
        classifier = UnifiedClassifier(fast_model=None, classification_mode="llm")
        result = await classifier.classify_routing("hello")
        assert result.task_complexity == "medium"

    @pytest.mark.asyncio
    async def test_routing_llm_failure_returns_safe_default(self) -> None:
        mock_model = MagicMock()
        mock_routing = AsyncMock()
        mock_routing.ainvoke = AsyncMock(side_effect=RuntimeError("API error"))
        mock_model.with_structured_output = MagicMock(return_value=mock_routing)

        classifier = UnifiedClassifier(fast_model=mock_model, classification_mode="llm")

        result = await classifier.classify_routing("hi")
        assert result.task_complexity == "medium"

    @pytest.mark.asyncio
    async def test_routing_patches_missing_chitchat_response(self) -> None:
        """Tier-1 guarantees chitchat_response when task_complexity is chitchat."""
        mock_model = MagicMock()
        mock_routing = AsyncMock()
        mock_routing.ainvoke = AsyncMock(return_value=RoutingResult(task_complexity="chitchat", chitchat_response=None))
        mock_model.with_structured_output = MagicMock(return_value=mock_routing)

        classifier = UnifiedClassifier(fast_model=mock_model, classification_mode="llm")

        result = await classifier.classify_routing("hello")
        assert result.task_complexity == "chitchat"
        assert result.chitchat_response is not None
        assert "Soothe" in result.chitchat_response

    @pytest.mark.asyncio
    async def test_routing_patches_empty_chitchat_response(self) -> None:
        mock_model = MagicMock()
        mock_routing = AsyncMock()
        mock_routing.ainvoke = AsyncMock(return_value=RoutingResult(task_complexity="chitchat", chitchat_response=""))
        mock_model.with_structured_output = MagicMock(return_value=mock_routing)

        classifier = UnifiedClassifier(fast_model=mock_model, classification_mode="llm")

        result = await classifier.classify_routing("hi")
        assert result.chitchat_response
        assert "Soothe" in result.chitchat_response

    @pytest.mark.asyncio
    async def test_routing_chinese_query_gets_chinese_fallback(self) -> None:
        mock_model = MagicMock()
        mock_routing = AsyncMock()
        mock_routing.ainvoke = AsyncMock(return_value=RoutingResult(task_complexity="chitchat", chitchat_response=None))
        mock_model.with_structured_output = MagicMock(return_value=mock_routing)

        classifier = UnifiedClassifier(fast_model=mock_model, classification_mode="llm")

        result = await classifier.classify_routing("你好")
        assert result.chitchat_response is not None
        assert "你好" in result.chitchat_response or "Soothe" in result.chitchat_response


# ---------------------------------------------------------------------------
# Tier-2 enrichment tests
# ---------------------------------------------------------------------------


class TestClassifyEnrichment:
    """Test tier-2 enrichment classification."""

    @pytest.mark.asyncio
    async def test_enrichment_search(self) -> None:
        mock_model = MagicMock()
        mock_enrichment = AsyncMock()
        mock_enrichment.ainvoke = AsyncMock(
            return_value=EnrichmentResult(
                is_plan_only=False,
                template_intent="search",
                capability_domains=["research"],
                reasoning="web search needed",
            )
        )
        mock_model.with_structured_output = MagicMock(return_value=mock_enrichment)

        classifier = UnifiedClassifier(fast_model=mock_model, classification_mode="llm")

        result = await classifier.classify_enrichment("latest Python docs", "medium")
        assert result.template_intent == "search"
        assert result.capability_domains == ["research"]

    @pytest.mark.asyncio
    async def test_enrichment_plan_only(self) -> None:
        mock_model = MagicMock()
        mock_enrichment = AsyncMock()
        mock_enrichment.ainvoke = AsyncMock(
            return_value=EnrichmentResult(is_plan_only=True, template_intent=None, reasoning="plan request")
        )
        mock_model.with_structured_output = MagicMock(return_value=mock_enrichment)

        classifier = UnifiedClassifier(fast_model=mock_model, classification_mode="llm")

        result = await classifier.classify_enrichment("plan only", "medium")
        assert result.is_plan_only is True

    @pytest.mark.asyncio
    async def test_enrichment_disabled_mode(self) -> None:
        classifier = UnifiedClassifier(fast_model=None, classification_mode="disabled")
        result = await classifier.classify_enrichment("test", "medium")
        assert result.reasoning == "Classification disabled"
        assert "research" in result.capability_domains

    @pytest.mark.asyncio
    async def test_enrichment_llm_failure_returns_defaults(self) -> None:
        mock_model = MagicMock()
        mock_enrichment = AsyncMock()
        mock_enrichment.ainvoke = AsyncMock(side_effect=RuntimeError("API error"))
        mock_model.with_structured_output = MagicMock(return_value=mock_enrichment)

        classifier = UnifiedClassifier(fast_model=mock_model, classification_mode="llm")

        result = await classifier.classify_enrichment("test query", "medium")
        assert "research" in result.capability_domains
        assert "failed" in result.reasoning.lower()

    @pytest.mark.asyncio
    async def test_enrichment_compose(self) -> None:
        mock_model = MagicMock()
        mock_enrichment = AsyncMock()
        mock_enrichment.ainvoke = AsyncMock(
            return_value=EnrichmentResult(
                template_intent="compose",
                capability_domains=["compose"],
                reasoning="agent creation",
            )
        )
        mock_model.with_structured_output = MagicMock(return_value=mock_enrichment)

        classifier = UnifiedClassifier(fast_model=mock_model, classification_mode="llm")

        result = await classifier.classify_enrichment("create a pdf subagent", "medium")
        assert result.template_intent == "compose"
        assert "compose" in result.capability_domains


# ---------------------------------------------------------------------------
# Two-tier integration tests (routing + enrichment -> UnifiedClassification)
# ---------------------------------------------------------------------------


class TestTwoTierIntegration:
    """Test the full two-tier flow: routing -> enrichment -> merge."""

    @pytest.mark.asyncio
    async def test_short_current_events_query(self) -> None:
        mock_model = MagicMock()
        mock_routing = AsyncMock()
        mock_routing.ainvoke = AsyncMock(return_value=RoutingResult(task_complexity="medium"))
        mock_enrichment = AsyncMock()
        mock_enrichment.ainvoke = AsyncMock(
            return_value=EnrichmentResult(template_intent="question", reasoning="research query")
        )
        mock_model.with_structured_output = MagicMock(side_effect=[mock_routing, mock_enrichment])

        classifier = UnifiedClassifier(fast_model=mock_model, classification_mode="llm")

        routing = await classifier.classify_routing("latest developments in Iran war")
        assert routing.task_complexity == "medium"

        enrichment = await classifier.classify_enrichment("latest developments in Iran war", "medium")
        merged = UnifiedClassification.from_tiers(routing, enrichment)
        assert merged.task_complexity == "medium"
        assert merged.template_intent == "question"

    @pytest.mark.asyncio
    async def test_simple_greeting_is_chitchat_with_response(self) -> None:
        mock_model = MagicMock()
        mock_routing = AsyncMock()
        mock_routing.ainvoke = AsyncMock(
            return_value=RoutingResult(task_complexity="chitchat", chitchat_response="Hello!")
        )
        mock_model.with_structured_output = MagicMock(return_value=mock_routing)

        classifier = UnifiedClassifier(fast_model=mock_model, classification_mode="llm")

        for greeting in ["hello", "hi", "good morning"]:
            result = await classifier.classify_routing(greeting)
            assert result.task_complexity == "chitchat"
            assert result.chitchat_response is not None


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    """Test edge cases and special scenarios."""

    @pytest.mark.asyncio
    async def test_empty_query_routing(self) -> None:
        mock_model = MagicMock()
        mock_routing = AsyncMock()
        mock_routing.ainvoke = AsyncMock(
            return_value=RoutingResult(task_complexity="chitchat", chitchat_response="Hello!")
        )
        mock_model.with_structured_output = MagicMock(return_value=mock_routing)

        classifier = UnifiedClassifier(fast_model=mock_model, classification_mode="llm")
        result = await classifier.classify_routing("")
        assert result.task_complexity == "chitchat"

    @pytest.mark.asyncio
    async def test_multilingual_plan_only(self) -> None:
        mock_model = MagicMock()
        mock_routing = AsyncMock()
        mock_routing.ainvoke = AsyncMock(return_value=RoutingResult(task_complexity="medium"))
        mock_enrichment = AsyncMock()
        mock_enrichment.ainvoke = AsyncMock(return_value=EnrichmentResult(is_plan_only=True, reasoning="plan request"))
        mock_model.with_structured_output = MagicMock(side_effect=[mock_routing, mock_enrichment])

        classifier = UnifiedClassifier(fast_model=mock_model, classification_mode="llm")
        routing = await classifier.classify_routing("只做计划,不要执行")
        enrichment = await classifier.classify_enrichment("只做计划,不要执行", routing.task_complexity)
        merged = UnifiedClassification.from_tiers(routing, enrichment)
        assert merged.is_plan_only is True

    @pytest.mark.asyncio
    async def test_very_long_query(self) -> None:
        mock_model = MagicMock()
        mock_routing = AsyncMock()
        mock_routing.ainvoke = AsyncMock(return_value=RoutingResult(task_complexity="complex"))
        mock_enrichment = AsyncMock()
        mock_enrichment.ainvoke = AsyncMock(
            return_value=EnrichmentResult(template_intent="implementation", reasoning="complex task")
        )
        mock_model.with_structured_output = MagicMock(side_effect=[mock_routing, mock_enrichment])

        classifier = UnifiedClassifier(fast_model=mock_model, classification_mode="llm")
        long_query = "implement a comprehensive system " * 50
        routing = await classifier.classify_routing(long_query)
        assert routing.task_complexity == "complex"
        enrichment = await classifier.classify_enrichment(long_query, "complex")
        merged = UnifiedClassification.from_tiers(routing, enrichment)
        assert merged.template_intent == "implementation"


# ---------------------------------------------------------------------------
# Chitchat response guarantee (via classify_routing)
# ---------------------------------------------------------------------------


class TestChitchatResponseGuarantee:
    """Test that chitchat_response is always populated for chitchat routing results."""

    @pytest.mark.asyncio
    async def test_existing_chitchat_response_not_overwritten(self) -> None:
        mock_model = MagicMock()
        mock_routing = AsyncMock()
        mock_routing.ainvoke = AsyncMock(
            return_value=RoutingResult(task_complexity="chitchat", chitchat_response="Hey there! I'm Soothe.")
        )
        mock_model.with_structured_output = MagicMock(return_value=mock_routing)

        classifier = UnifiedClassifier(fast_model=mock_model, classification_mode="llm")
        result = await classifier.classify_routing("hi")
        assert result.chitchat_response == "Hey there! I'm Soothe."

    @pytest.mark.asyncio
    async def test_custom_assistant_name_in_fallback(self) -> None:
        mock_model = MagicMock()
        mock_routing = AsyncMock()
        mock_routing.ainvoke = AsyncMock(return_value=RoutingResult(task_complexity="chitchat", chitchat_response=None))
        mock_model.with_structured_output = MagicMock(return_value=mock_routing)

        classifier = UnifiedClassifier(fast_model=mock_model, classification_mode="llm", assistant_name="Atlas")
        result = await classifier.classify_routing("hello")
        assert "Atlas" in result.chitchat_response

    @pytest.mark.asyncio
    async def test_non_chitchat_routing_has_no_response(self) -> None:
        mock_model = MagicMock()
        mock_routing = AsyncMock()
        mock_routing.ainvoke = AsyncMock(return_value=RoutingResult(task_complexity="medium"))
        mock_model.with_structured_output = MagicMock(return_value=mock_routing)

        classifier = UnifiedClassifier(fast_model=mock_model, classification_mode="llm")
        result = await classifier.classify_routing("what is quantum computing")
        assert result.task_complexity == "medium"
        assert result.chitchat_response is None


# ---------------------------------------------------------------------------
# Helper tests
# ---------------------------------------------------------------------------


class TestLooksChinese:
    """Test the _looks_chinese helper."""

    def test_chinese_text(self) -> None:
        assert _looks_chinese("你好") is True
        assert _looks_chinese("谢谢你的帮助") is True

    def test_english_text(self) -> None:
        assert _looks_chinese("hello") is False
        assert _looks_chinese("how are you") is False

    def test_mixed_text(self) -> None:
        assert _looks_chinese("hello 你好") is True

    def test_empty_text(self) -> None:
        assert _looks_chinese("") is False


class TestDefaultClassification:
    """Test default classification logic."""

    def test_default_classification(self) -> None:
        classifier = UnifiedClassifier(fast_model=None, classification_mode="disabled")
        result = classifier._default_classification("Test reason")
        assert result.task_complexity == "medium"
        assert result.is_plan_only is False
        assert result.reasoning == "Test reason"

    def test_default_classification_default_reason(self) -> None:
        classifier = UnifiedClassifier(fast_model=None, classification_mode="disabled")
        result = classifier._default_classification()
        assert result.reasoning == "Default"


# ---------------------------------------------------------------------------
# Template intent tests
# ---------------------------------------------------------------------------


class TestTemplateIntent:
    """Test template intent via tier-2 enrichment."""

    @pytest.mark.asyncio
    async def test_question_intent(self) -> None:
        mock_model = MagicMock()
        mock_enrichment = AsyncMock()
        mock_enrichment.ainvoke = AsyncMock(
            return_value=EnrichmentResult(template_intent="question", reasoning="topic question")
        )
        mock_model.with_structured_output = MagicMock(return_value=mock_enrichment)

        classifier = UnifiedClassifier(fast_model=mock_model, classification_mode="llm")
        result = await classifier.classify_enrichment("what is machine learning", "medium")
        assert result.template_intent == "question"

    @pytest.mark.asyncio
    async def test_search_intent(self) -> None:
        mock_model = MagicMock()
        mock_enrichment = AsyncMock()
        mock_enrichment.ainvoke = AsyncMock(
            return_value=EnrichmentResult(template_intent="search", reasoning="search request")
        )
        mock_model.with_structured_output = MagicMock(return_value=mock_enrichment)

        classifier = UnifiedClassifier(fast_model=mock_model, classification_mode="llm")
        result = await classifier.classify_enrichment("find information about Python", "medium")
        assert result.template_intent == "search"

    @pytest.mark.asyncio
    async def test_compose_intent(self) -> None:
        mock_model = MagicMock()
        mock_enrichment = AsyncMock()
        mock_enrichment.ainvoke = AsyncMock(
            return_value=EnrichmentResult(
                template_intent="compose",
                capability_domains=["compose"],
                reasoning="agent creation",
            )
        )
        mock_model.with_structured_output = MagicMock(return_value=mock_enrichment)

        classifier = UnifiedClassifier(fast_model=mock_model, classification_mode="llm")
        result = await classifier.classify_enrichment("create a subagent that handles pdf and docx", "medium")
        assert result.template_intent == "compose"
        assert "compose" in result.capability_domains

    @pytest.mark.asyncio
    async def test_chitchat_routing_has_no_intent(self) -> None:
        """Chitchat only uses tier-1; enrichment is never called."""
        routing = RoutingResult(task_complexity="chitchat", chitchat_response="Hi there!")
        merged = UnifiedClassification.from_tiers(routing, enrichment=None)
        assert merged.template_intent is None
        assert merged.chitchat_response == "Hi there!"
