"""Tests for unified LLM-based classification system (RFC-0012)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from soothe.core.unified_classifier import UnifiedClassification, UnifiedClassifier, _looks_chinese


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
        assert classification.chitchat_response is None
        assert classification.preferred_subagent is None

    def test_preferred_subagent_field(self) -> None:
        """Test preferred_subagent is stored when set."""
        classification = UnifiedClassification(
            task_complexity="medium",
            is_plan_only=False,
            template_intent="implementation",
            preferred_subagent="claude",
        )

        assert classification.preferred_subagent == "claude"

    def test_chitchat_response_field(self) -> None:
        """Test chitchat_response is populated for chitchat queries."""
        classification = UnifiedClassification(
            task_complexity="chitchat",
            is_plan_only=False,
            chitchat_response="Hello! How can I help you today?",
        )

        assert classification.chitchat_response == "Hello! How can I help you today?"


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
    async def test_simple_greeting_is_chitchat_with_response(self) -> None:
        """Test simple greetings are classified as chitchat with piggybacked response."""
        mock_model = MagicMock()
        mock_structured = AsyncMock()
        mock_structured.ainvoke = AsyncMock(
            return_value=UnifiedClassification(
                task_complexity="chitchat",
                is_plan_only=False,
                template_intent=None,
                chitchat_response="Hello! How can I help you today?",
                reasoning="Simple greeting",
            )
        )
        mock_model.with_structured_output = MagicMock(return_value=mock_structured)

        classifier = UnifiedClassifier(fast_model=mock_model, classification_mode="llm")

        for greeting in ["hello", "hi", "good morning", "你好", "您好"]:
            result = await classifier.classify(greeting)
            assert result.task_complexity == "chitchat"
            assert result.chitchat_response is not None

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
                chitchat_response="Hello! How can I help?",
                reasoning="Empty query",
            )
        )
        mock_model.with_structured_output = MagicMock(return_value=mock_structured)

        classifier = UnifiedClassifier(fast_model=mock_model, classification_mode="llm")

        result = await classifier.classify("")
        assert result.task_complexity == "chitchat"
        assert result.is_plan_only is False

    def test_assistant_name_passed_to_classifier(self) -> None:
        """Test that assistant_name is stored on the classifier."""
        mock_model = MagicMock()
        mock_model.with_structured_output = MagicMock(return_value=mock_model)

        classifier = UnifiedClassifier(
            fast_model=mock_model,
            classification_mode="llm",
            assistant_name="TestBot",
        )
        assert classifier._assistant_name == "TestBot"

    def test_default_assistant_name(self) -> None:
        """Test default assistant_name is Soothe."""
        classifier = UnifiedClassifier(fast_model=None, classification_mode="disabled")
        assert classifier._assistant_name == "Soothe"

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


class TestChitchatResponseGuarantee:
    """Test that chitchat_response is always populated for chitchat queries."""

    @pytest.mark.asyncio
    async def test_missing_chitchat_response_is_patched(self) -> None:
        """When LLM returns chitchat without chitchat_response, classifier patches it."""
        mock_model = MagicMock()
        mock_structured = AsyncMock()
        mock_structured.ainvoke = AsyncMock(
            return_value=UnifiedClassification(
                task_complexity="chitchat",
                is_plan_only=False,
                template_intent=None,
                chitchat_response=None,
                reasoning="Simple greeting",
            )
        )
        mock_model.with_structured_output = MagicMock(return_value=mock_structured)

        classifier = UnifiedClassifier(fast_model=mock_model, classification_mode="llm")

        result = await classifier.classify("hello")
        assert result.task_complexity == "chitchat"
        assert result.chitchat_response is not None
        assert len(result.chitchat_response) > 0
        assert "Soothe" in result.chitchat_response

    @pytest.mark.asyncio
    async def test_empty_string_chitchat_response_is_patched(self) -> None:
        """When LLM returns empty-string chitchat_response, classifier patches it."""
        mock_model = MagicMock()
        mock_structured = AsyncMock()
        mock_structured.ainvoke = AsyncMock(
            return_value=UnifiedClassification(
                task_complexity="chitchat",
                is_plan_only=False,
                template_intent=None,
                chitchat_response="",
                reasoning="Greeting",
            )
        )
        mock_model.with_structured_output = MagicMock(return_value=mock_structured)

        classifier = UnifiedClassifier(fast_model=mock_model, classification_mode="llm")

        result = await classifier.classify("hi")
        assert result.chitchat_response
        assert "Soothe" in result.chitchat_response

    @pytest.mark.asyncio
    async def test_existing_chitchat_response_not_overwritten(self) -> None:
        """When LLM provides chitchat_response, classifier preserves it."""
        mock_model = MagicMock()
        mock_structured = AsyncMock()
        mock_structured.ainvoke = AsyncMock(
            return_value=UnifiedClassification(
                task_complexity="chitchat",
                is_plan_only=False,
                template_intent=None,
                chitchat_response="Hey there! I'm Soothe.",
                reasoning="Greeting",
            )
        )
        mock_model.with_structured_output = MagicMock(return_value=mock_structured)

        classifier = UnifiedClassifier(fast_model=mock_model, classification_mode="llm")

        result = await classifier.classify("hi")
        assert result.chitchat_response == "Hey there! I'm Soothe."

    @pytest.mark.asyncio
    async def test_chinese_query_gets_chinese_fallback(self) -> None:
        """Chinese chitchat query gets a Chinese fallback response."""
        mock_model = MagicMock()
        mock_structured = AsyncMock()
        mock_structured.ainvoke = AsyncMock(
            return_value=UnifiedClassification(
                task_complexity="chitchat",
                is_plan_only=False,
                template_intent=None,
                chitchat_response=None,
                reasoning="Chinese greeting",
            )
        )
        mock_model.with_structured_output = MagicMock(return_value=mock_structured)

        classifier = UnifiedClassifier(fast_model=mock_model, classification_mode="llm")

        result = await classifier.classify("你好")
        assert result.chitchat_response is not None
        assert "你好" in result.chitchat_response or "Soothe" in result.chitchat_response

    @pytest.mark.asyncio
    async def test_custom_assistant_name_in_fallback(self) -> None:
        """Fallback response uses the configured assistant name."""
        mock_model = MagicMock()
        mock_structured = AsyncMock()
        mock_structured.ainvoke = AsyncMock(
            return_value=UnifiedClassification(
                task_complexity="chitchat",
                is_plan_only=False,
                chitchat_response=None,
                reasoning="Greeting",
            )
        )
        mock_model.with_structured_output = MagicMock(return_value=mock_structured)

        classifier = UnifiedClassifier(fast_model=mock_model, classification_mode="llm", assistant_name="Atlas")

        result = await classifier.classify("hello")
        assert "Atlas" in result.chitchat_response

    @pytest.mark.asyncio
    async def test_non_chitchat_not_patched(self) -> None:
        """Medium/complex queries are not affected by the chitchat guarantee."""
        mock_model = MagicMock()
        mock_structured = AsyncMock()
        mock_structured.ainvoke = AsyncMock(
            return_value=UnifiedClassification(
                task_complexity="medium",
                is_plan_only=False,
                template_intent="question",
                chitchat_response=None,
                reasoning="Research question",
            )
        )
        mock_model.with_structured_output = MagicMock(return_value=mock_structured)

        classifier = UnifiedClassifier(fast_model=mock_model, classification_mode="llm")

        result = await classifier.classify("what is quantum computing")
        assert result.task_complexity == "medium"
        assert result.chitchat_response is None


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
    async def test_compose_intent_classification(self) -> None:
        """Test agent/skill creation queries get compose template_intent."""
        mock_model = MagicMock()
        mock_structured = AsyncMock()
        mock_structured.ainvoke = AsyncMock(
            return_value=UnifiedClassification(
                task_complexity="medium",
                is_plan_only=False,
                template_intent="compose",
                capability_domains=["compose"],
                reasoning="Create a new subagent",
            )
        )
        mock_model.with_structured_output = MagicMock(return_value=mock_structured)

        classifier = UnifiedClassifier(fast_model=mock_model, classification_mode="llm")

        result = await classifier.classify("create a subagent that handles pdf and docx")
        assert result.task_complexity == "medium"
        assert result.template_intent == "compose"
        assert "compose" in result.capability_domains

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
                chitchat_response="Hi there!",
                reasoning="Simple greeting",
            )
        )
        mock_model.with_structured_output = MagicMock(return_value=mock_structured)

        classifier = UnifiedClassifier(fast_model=mock_model, classification_mode="llm")

        result = await classifier.classify("hello")
        assert result.task_complexity == "chitchat"
        assert result.template_intent is None
        assert result.chitchat_response == "Hi there!"


class TestPreferredSubagent:
    """Test preferred_subagent detection and routing."""

    @pytest.mark.asyncio
    async def test_explicit_claude_request_sets_preferred_subagent(self) -> None:
        """When user explicitly names claude, preferred_subagent is set."""
        mock_model = MagicMock()
        mock_structured = AsyncMock()
        mock_structured.ainvoke = AsyncMock(
            return_value=UnifiedClassification(
                task_complexity="medium",
                is_plan_only=False,
                template_intent="implementation",
                preferred_subagent="claude",
                reasoning="User explicitly requested claude subagent",
            )
        )
        mock_model.with_structured_output = MagicMock(return_value=mock_structured)

        classifier = UnifiedClassifier(fast_model=mock_model, classification_mode="llm")

        result = await classifier.classify("使用claude编写脚本扫描这个项目的所有markdown文件数量")
        assert result.task_complexity == "medium"
        assert result.preferred_subagent == "claude"

    @pytest.mark.asyncio
    async def test_no_explicit_subagent_leaves_preferred_null(self) -> None:
        """When user doesn't name a subagent, preferred_subagent stays null."""
        mock_model = MagicMock()
        mock_structured = AsyncMock()
        mock_structured.ainvoke = AsyncMock(
            return_value=UnifiedClassification(
                task_complexity="medium",
                is_plan_only=False,
                template_intent="implementation",
                preferred_subagent=None,
                reasoning="Standard implementation task",
            )
        )
        mock_model.with_structured_output = MagicMock(return_value=mock_structured)

        classifier = UnifiedClassifier(fast_model=mock_model, classification_mode="llm")

        result = await classifier.classify("write a script to count markdown files")
        assert result.preferred_subagent is None

    @pytest.mark.asyncio
    async def test_explicit_browser_request(self) -> None:
        """When user explicitly names browser subagent."""
        mock_model = MagicMock()
        mock_structured = AsyncMock()
        mock_structured.ainvoke = AsyncMock(
            return_value=UnifiedClassification(
                task_complexity="medium",
                is_plan_only=False,
                template_intent="implementation",
                preferred_subagent="browser",
                capability_domains=["browse"],
                reasoning="User requested browser subagent",
            )
        )
        mock_model.with_structured_output = MagicMock(return_value=mock_structured)

        classifier = UnifiedClassifier(fast_model=mock_model, classification_mode="llm")

        result = await classifier.classify("用browser打开github.com")
        assert result.preferred_subagent == "browser"

    def test_default_classification_has_no_preferred_subagent(self) -> None:
        """Default classification has preferred_subagent=None."""
        classifier = UnifiedClassifier(fast_model=None, classification_mode="disabled")

        result = classifier._default_classification("Test reason")
        assert result.preferred_subagent is None
