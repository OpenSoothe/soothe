"""Tests for intake classification (RFC-630 / RFC-904)."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from soothe_sdk.intention.models import TaskComplexity

from soothe.sloop.intention import IntentClassification, IntentClassifier
from soothe.sloop.intention.coordinator import IntakeResult
from soothe.sloop.intention.models import (
    IntakeConfidence,
    IntakeLabel,
    IntakeLLMResult,
    IntakeScope,
    ResponseLanguage,
    derive_task_complexity_from_intake,
    intent_classification_from_intake_scope,
    parse_intake_scope,
)
from soothe.sloop.intention.prompts import (
    INTAKE_CLASSIFY_HUMAN_TASK,
    INTAKE_CLASSIFY_SYSTEM_PROMPT,
)


class TestIntentClassificationModel:
    """Test IntentClassification Pydantic model."""

    def test_model_creation_trivial(self) -> None:
        intent = IntentClassification(
            intake_label=IntakeLabel.TRIVIAL,
            task_complexity=TaskComplexity.MINIMAL,
        )
        assert intent.intake_label == IntakeLabel.TRIVIAL

    def test_model_creation_complex(self) -> None:
        intent = IntentClassification(
            intake_label=IntakeLabel.COMPLEX,
            task_complexity=TaskComplexity.COMPLEX,
        )
        assert intent.intake_label == IntakeLabel.COMPLEX


class TestDeriveTaskComplexityFromIntake:
    """``derive_task_complexity_from_intake`` maps client-forced scope labels."""

    def test_chitchat_maps_to_minimal(self) -> None:
        assert derive_task_complexity_from_intake(IntakeLabel.CHITCHAT) == TaskComplexity.MINIMAL

    def test_trivial_maps_to_minimal(self) -> None:
        assert derive_task_complexity_from_intake(IntakeLabel.TRIVIAL) == TaskComplexity.MINIMAL

    def test_simple_maps_to_simple(self) -> None:
        assert derive_task_complexity_from_intake(IntakeLabel.SIMPLE) == TaskComplexity.SIMPLE

    def test_complex_maps_to_complex(self) -> None:
        assert derive_task_complexity_from_intake(IntakeLabel.COMPLEX) == TaskComplexity.COMPLEX


class TestClientIntakeScope:
    """Wire ``intake_scope`` parse + forced IntentClassification helpers."""

    def test_parse_intake_scope_normalizes(self) -> None:
        assert parse_intake_scope(None) is None
        assert parse_intake_scope("  ") is None
        assert parse_intake_scope("Simple") == IntakeScope.SIMPLE

    def test_parse_intake_scope_rejects_invalid(self) -> None:
        with pytest.raises(ValueError, match="intake_scope"):
            parse_intake_scope("chitchat")

    def test_intent_classification_from_intake_scope(self) -> None:
        intent = intent_classification_from_intake_scope(IntakeScope.TRIVIAL)
        assert intent.intake_label == IntakeLabel.TRIVIAL
        assert intent.task_complexity == TaskComplexity.MINIMAL
        assert "intake_scope=trivial" in (intent.reasoning or "")


class TestIntakePrompts:
    """Prompt content guards for intake classification."""

    def test_intake_prompt_has_social_and_work_rules(self) -> None:
        assert "SOCIAL" in INTAKE_CLASSIFY_SYSTEM_PROMPT
        assert "WORK" in INTAKE_CLASSIFY_SYSTEM_PROMPT
        assert "is_task" in INTAKE_CLASSIFY_SYSTEM_PROMPT
        assert "social_response" in INTAKE_CLASSIFY_SYSTEM_PROMPT
        assert "response_language" in INTAKE_CLASSIFY_SYSTEM_PROMPT
        assert "PRIOR_RESPONSE_LANGUAGE" in INTAKE_CLASSIFY_SYSTEM_PROMPT

    def test_intake_prompt_requires_friendly_reasoning(self) -> None:
        prompt = INTAKE_CLASSIFY_SYSTEM_PROMPT
        assert "This is a request" in prompt
        assert "Here is a goal" in prompt
        assert "classification notes" not in prompt
        assert "friendly TUI line" in prompt
        assert "≤25 words" in prompt
        assert "≤15 words" not in prompt

    def test_intake_human_task_is_compact(self) -> None:
        assert INTAKE_CLASSIFY_HUMAN_TASK == "Classify the user message above. JSON only."
        assert "Identity replies" not in INTAKE_CLASSIFY_HUMAN_TASK

    def test_intake_prompt_has_continuation_led_pivot_examples(self) -> None:
        assert "Continue and fix the failing unit tests" in INTAKE_CLASSIFY_SYSTEM_PROMPT
        assert "continuation-led pivot" in INTAKE_CLASSIFY_SYSTEM_PROMPT.lower()


@pytest.mark.asyncio
class TestIntakeClassifier:
    """Test the intake classifier with mocked LLM (RFC-904)."""

    def _mock_intake_result(
        self,
        *,
        is_task: bool,
        reasoning: str | None = None,
        social_response: str | None = None,
    ) -> IntakeResult:
        intake_result = IntakeLLMResult(
            is_task=is_task,
            confidence=IntakeConfidence.HIGH,
            social_response=social_response,
            reasoning="test" if reasoning is None else reasoning,
        )
        return IntakeResult(intake_result)

    async def test_task_intake_uses_complex_compatibility_label(self) -> None:
        classifier = IntentClassifier(model=MagicMock(), assistant_name="TestBot")
        mock_result = self._mock_intake_result(is_task=True)
        with patch.object(
            classifier._coordinator, "classify", new_callable=AsyncMock
        ) as mock_classify:
            mock_classify.return_value = mock_result
            result = await classifier.classify_intake("summarize readme")
        assert result.intake_label == IntakeLabel.COMPLEX

    async def test_weather_query_uses_llm_intake(self) -> None:
        classifier = IntentClassifier(model=MagicMock(), assistant_name="TestBot")
        mock_result = self._mock_intake_result(is_task=True)
        with patch.object(
            classifier._coordinator, "classify", new_callable=AsyncMock
        ) as mock_classify:
            mock_classify.return_value = mock_result
            result = await classifier.classify_intake("北京今天的天气")
        mock_classify.assert_awaited_once()
        assert result.intake_label == IntakeLabel.COMPLEX

    async def test_complex_intake_classification(self) -> None:
        classifier = IntentClassifier(model=MagicMock(), assistant_name="TestBot")
        mock_result = self._mock_intake_result(
            is_task=True,
            reasoning="multi-step refactor",
        )
        with patch.object(
            classifier._coordinator, "classify", new_callable=AsyncMock
        ) as mock_classify:
            mock_classify.return_value = mock_result
            result = await classifier.classify_intake("Refactor the persistence layer")
        assert result.intake_label == IntakeLabel.COMPLEX

    async def test_long_query_reaches_llm(self) -> None:
        classifier = IntentClassifier(model=MagicMock(), assistant_name="TestBot")
        long_query = (
            "Please help me refactor the authentication module to use OAuth2 "
            "with PKCE flow and update all the tests"
        )
        mock_result = self._mock_intake_result(is_task=True)
        with patch.object(
            classifier._coordinator, "classify", new_callable=AsyncMock
        ) as mock_classify:
            mock_classify.return_value = mock_result
            result = await classifier.classify_intake(long_query)
        mock_classify.assert_awaited()
        assert result.intake_label == IntakeLabel.COMPLEX

    async def test_identity_query_uses_llm_intake(self) -> None:
        classifier = IntentClassifier(model=MagicMock(), assistant_name="Soothe")
        mock_result = self._mock_intake_result(
            is_task=False,
            social_response=(
                "I'm Soothe, an AI assistant invented by Dr. Xiaming Chen. "
                "How can I help you today?"
            ),
        )
        with patch.object(
            classifier._coordinator, "classify", new_callable=AsyncMock
        ) as mock_classify:
            mock_classify.return_value = mock_result
            result = await classifier.classify_intake("who are u")
        mock_classify.assert_awaited_once()
        assert result.intake_label == IntakeLabel.CHITCHAT
        assert result.chitchat_response == (
            "I'm Soothe, an AI assistant invented by Dr. Xiaming Chen. How can I help you today?"
        )

    async def test_fallback_defaults_to_complex(self) -> None:
        classifier = IntentClassifier(model=None, assistant_name="TestBot")
        result = await classifier.classify_intake("do something")
        assert result.intake_label == IntakeLabel.COMPLEX
        assert result.task_complexity == TaskComplexity.COMPLEX
        assert result.reasoning is not None

    async def test_patch_missing_reasoning_uses_first_person(self) -> None:
        classifier = IntentClassifier(model=MagicMock(), assistant_name="TestBot")
        mock_result = self._mock_intake_result(is_task=True, reasoning="")
        with patch.object(
            classifier._coordinator, "classify", new_callable=AsyncMock
        ) as mock_classify:
            mock_classify.return_value = mock_result
            result = await classifier.classify_intake("summarize readme")
        assert result.reasoning == "I'll use tools to work through this goal."


class TestSocialToIntent:
    """Sync helpers on IntentClassifier (no event loop)."""

    def test_social_to_intent_propagates_response_language(self) -> None:
        classifier = IntentClassifier(model=MagicMock(), assistant_name="Soothe")
        intake_result = IntakeLLMResult(
            is_task=False,
            confidence=IntakeConfidence.HIGH,
            social_response="你好！",
            response_language=ResponseLanguage.ZH,
            reasoning="greeting",
        )
        intent = classifier.social_to_intent(intake_result, "你好")
        assert intent.response_language == ResponseLanguage.ZH
