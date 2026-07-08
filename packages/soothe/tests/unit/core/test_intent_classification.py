"""Tests for two-pass intake classification (RFC-630, IG-554)."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from soothe.foundation.sloop.intention import IntentClassification, IntentClassifier, TaskComplexity
from soothe.foundation.sloop.intention.models import (
    IntakeLabel,
    IntakePass1Confidence,
    IntakePass1LLMResult,
    IntakePass2LLMResult,
    IntakeScope,
    derive_task_complexity_from_intake,
)
from soothe.foundation.sloop.intention.prompts import (
    INTAKE_PASS1_HUMAN_TASK,
    INTAKE_PASS1_SYSTEM_PROMPT,
    INTAKE_PASS2_HUMAN_TASK,
    INTAKE_PASS2_SYSTEM_PROMPT,
)
from soothe.foundation.sloop.intention.two_pass_coordinator import TwoPassIntakeResult


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
            goal_description="Build a web scraper",
            task_complexity=TaskComplexity.COMPLEX,
        )
        assert intent.intake_label == IntakeLabel.COMPLEX
        assert intent.goal_description == "Build a web scraper"


class TestDeriveTaskComplexityFromIntake:
    """``task_complexity`` is derived from ``intake_label``, not LLM output."""

    def test_chitchat_maps_to_minimal(self) -> None:
        assert derive_task_complexity_from_intake(IntakeLabel.CHITCHAT) == TaskComplexity.MINIMAL

    def test_trivial_maps_to_minimal(self) -> None:
        assert derive_task_complexity_from_intake(IntakeLabel.TRIVIAL) == TaskComplexity.MINIMAL

    def test_simple_maps_to_simple(self) -> None:
        assert derive_task_complexity_from_intake(IntakeLabel.SIMPLE) == TaskComplexity.SIMPLE

    def test_complex_maps_to_complex(self) -> None:
        assert derive_task_complexity_from_intake(IntakeLabel.COMPLEX) == TaskComplexity.COMPLEX


class TestTwoPassPrompts:
    """Prompt content guards for two-pass intake (IG-554)."""

    def test_pass1_prompt_has_social_and_work_rules(self) -> None:
        assert "SOCIAL" in INTAKE_PASS1_SYSTEM_PROMPT
        assert "WORK" in INTAKE_PASS1_SYSTEM_PROMPT
        assert "is_task" in INTAKE_PASS1_SYSTEM_PROMPT
        assert "social_response" in INTAKE_PASS1_SYSTEM_PROMPT

    def test_pass2_prompt_has_scope_labels(self) -> None:
        for label in ("trivial", "simple", "complex"):
            assert label in INTAKE_PASS2_SYSTEM_PROMPT
        assert "chitchat" not in INTAKE_PASS2_SYSTEM_PROMPT.lower()

    def test_pass1_human_task_is_compact(self) -> None:
        assert INTAKE_PASS1_HUMAN_TASK == (
            "Classify above. Identity replies must use the configured assistant name. JSON only."
        )

    def test_pass2_human_task_mentions_scope(self) -> None:
        assert "scope" in INTAKE_PASS2_HUMAN_TASK.lower()

    def test_pass2_prompt_requires_first_person_reasoning(self) -> None:
        prompt = INTAKE_PASS2_SYSTEM_PROMPT
        assert "first-person" in prompt
        assert "I'll / Let me" in prompt
        assert "multi_phase" in prompt
        assert "wire_subagent" in prompt
        assert "first scan the repo and then run tests" in prompt
        assert "use browser_use for weather" in prompt


@pytest.mark.asyncio
class TestIntakeClassifier:
    """Test the two-pass intake classifier with mocked LLM (RFC-630, IG-554)."""

    def _mock_two_pass_result(
        self,
        *,
        is_task: bool,
        intake_label: IntakeLabel,
        goal_description: str | None = None,
        reasoning: str | None = None,
        social_response: str | None = None,
    ) -> TwoPassIntakeResult:
        pass1 = IntakePass1LLMResult(
            is_task=is_task,
            confidence=IntakePass1Confidence.HIGH,
            social_response=social_response,
            reasoning=reasoning or "test",
        )
        if not is_task:
            return TwoPassIntakeResult(pass1)
        pass2 = IntakePass2LLMResult(
            scope=IntakeScope(intake_label),
            goal_description=goal_description or "goal",
            reasoning=reasoning if reasoning is not None else "test",
        )
        return TwoPassIntakeResult(pass1, pass2)

    async def test_trivial_intake_classification(self) -> None:
        classifier = IntentClassifier(model=MagicMock(), assistant_name="TestBot")
        mock_result = self._mock_two_pass_result(
            is_task=True,
            intake_label=IntakeLabel.TRIVIAL,
        )
        with patch.object(
            classifier._two_pass, "classify", new_callable=AsyncMock
        ) as mock_classify:
            mock_classify.return_value = mock_result
            result = await classifier.classify_intake("summarize readme")
        assert result.intake_label == IntakeLabel.TRIVIAL

    async def test_weather_query_uses_llm_intake(self) -> None:
        classifier = IntentClassifier(model=MagicMock(), assistant_name="TestBot")
        mock_result = self._mock_two_pass_result(
            is_task=True,
            intake_label=IntakeLabel.TRIVIAL,
            goal_description="北京今天的天气",
        )
        with patch.object(
            classifier._two_pass, "classify", new_callable=AsyncMock
        ) as mock_classify:
            mock_classify.return_value = mock_result
            result = await classifier.classify_intake("北京今天的天气")
        mock_classify.assert_awaited_once()
        assert result.intake_label == IntakeLabel.TRIVIAL

    async def test_complex_intake_classification(self) -> None:
        classifier = IntentClassifier(model=MagicMock(), assistant_name="TestBot")
        mock_result = self._mock_two_pass_result(
            is_task=True,
            intake_label=IntakeLabel.COMPLEX,
            goal_description="Refactor persistence",
            reasoning="multi-step refactor",
        )
        with patch.object(
            classifier._two_pass, "classify", new_callable=AsyncMock
        ) as mock_classify:
            mock_classify.return_value = mock_result
            result = await classifier.classify_intake("Refactor the persistence layer")
        assert result.intake_label == IntakeLabel.COMPLEX
        assert result.goal_description == "Refactor persistence"

    async def test_long_query_reaches_llm(self) -> None:
        classifier = IntentClassifier(model=MagicMock(), assistant_name="TestBot")
        long_query = (
            "Please help me refactor the authentication module to use OAuth2 "
            "with PKCE flow and update all the tests"
        )
        mock_result = self._mock_two_pass_result(
            is_task=True,
            intake_label=IntakeLabel.TRIVIAL,
        )
        with patch.object(
            classifier._two_pass, "classify", new_callable=AsyncMock
        ) as mock_classify:
            mock_classify.return_value = mock_result
            result = await classifier.classify_intake(long_query)
        mock_classify.assert_awaited()
        assert result.intake_label == IntakeLabel.TRIVIAL

    async def test_identity_query_uses_llm_intake(self) -> None:
        classifier = IntentClassifier(model=MagicMock(), assistant_name="Soothe")
        mock_result = self._mock_two_pass_result(
            is_task=False,
            intake_label=IntakeLabel.CHITCHAT,
            social_response=(
                "I'm Soothe, an AI assistant invented by Dr. Xiaming Chen. "
                "How can I help you today?"
            ),
        )
        with patch.object(
            classifier._two_pass, "classify", new_callable=AsyncMock
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
        mock_result = self._mock_two_pass_result(
            is_task=True,
            intake_label=IntakeLabel.SIMPLE,
            goal_description="summarize readme",
            reasoning="",
        )
        with patch.object(
            classifier._two_pass, "classify", new_callable=AsyncMock
        ) as mock_classify:
            mock_classify.return_value = mock_result
            result = await classifier.classify_intake("summarize readme")
        assert result.reasoning == "I'll use tools to work through this goal."
