"""Tests for semantic risk classifier (IG-433)."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from soothe.config.models import SemanticRiskConfig
from soothe.core.goal_engine.semantic_risk_classifier import (
    RiskAssessment,
    RiskCache,
    clear_risk_cache,
    evaluate_criticality_semantic,
    risk_assessment_to_criticality,
    semantic_evaluate_risk,
)


class TestRiskCache:
    def test_exact_match_returns_cached(self) -> None:
        cache = RiskCache()
        assessment = RiskAssessment(
            risk_level="high",
            confidence=0.9,
            reasoning="Cached assessment",
        )
        cache.store("Deploy production", [0.1, 0.2], assessment)

        # Exact match should return cached
        result = cache.lookup_exact("Deploy production")
        assert result is not None
        assert result.risk_level == "high"

        # Different text should not match
        result = cache.lookup_exact("Deploy staging")
        assert result is None

    def test_normalized_exact_match(self) -> None:
        cache = RiskCache()
        assessment = RiskAssessment(risk_level="low", confidence=0.9)
        cache.store("Deploy Test API", [0.1, 0.2], assessment)

        # Case-insensitive match
        result = cache.lookup_exact("deploy test api")
        assert result is not None
        assert result.risk_level == "low"

    def test_lru_bounded(self) -> None:
        cache = RiskCache(max_entries=5)
        for i in range(10):
            cache.store(f"Goal {i}", [float(i)], RiskAssessment(risk_level="low"))
        assert len(cache.entries) == 5
        # Should retain last 5
        assert cache.entries[0].description == "Goal 5"


class TestRiskAssessmentToCriticality:
    def test_high_maps_to_must(self) -> None:
        assessment = RiskAssessment(
            risk_level="high",
            confidence=0.9,
            reasoning="Deletes production data",
            requires_confirmation=True,
        )
        result = risk_assessment_to_criticality(assessment)
        assert result.level == "must"
        assert result.requires_confirmation is True

    def test_low_maps_to_nice(self) -> None:
        assessment = RiskAssessment(
            risk_level="low",
            confidence=0.95,
            reasoning="Read-only documentation review",
        )
        result = risk_assessment_to_criticality(assessment)
        assert result.level == "nice"
        assert result.requires_confirmation is False

    def test_critical_maps_to_must(self) -> None:
        assessment = RiskAssessment(
            risk_level="critical",
            confidence=0.95,
            reasoning="Irreversible operation",
        )
        result = risk_assessment_to_criticality(assessment)
        assert result.level == "must"


@pytest.mark.asyncio
class TestSemanticEvaluateRisk:
    async def test_llm_structured_assessment(self) -> None:
        clear_risk_cache()
        mock_model = MagicMock()
        assessment = RiskAssessment(
            risk_level="medium",
            confidence=0.8,
            reasoning="Touches external API",
            requires_confirmation=True,
        )
        structured = MagicMock()
        structured.ainvoke = AsyncMock(return_value=assessment)
        mock_model.with_structured_output = MagicMock(return_value=structured)

        result = await semantic_evaluate_risk(
            "Sync user profiles with CRM",
            50,
            mock_model,
            config=SemanticRiskConfig(cache_enabled=False),
        )
        assert result.risk_level == "medium"
        assert result.confidence >= 0.5

    async def test_exact_cache_hit(self) -> None:
        """Exact text match should return cached assessment."""
        cache = RiskCache()
        cached_assessment = RiskAssessment(
            risk_level="high",
            confidence=0.9,
            reasoning="Cached",
        )
        cache.store("Deploy production database", [0.5, 0.5], cached_assessment)

        mock_model = MagicMock()  # Should not be called

        result = await semantic_evaluate_risk(
            "Deploy production database",
            50,
            mock_model,
            config=SemanticRiskConfig(cache_enabled=True),
            cache=cache,
        )
        assert result.risk_level == "high"
        assert result.reasoning == "Cached"
        # LLM should not have been called
        mock_model.with_structured_output.assert_not_called()

    async def test_llm_failure_returns_low_confidence_fallback(self) -> None:
        """LLM failure should return assessment that triggers keyword fallback."""
        mock_model = AsyncMock()
        mock_model.with_structured_output.side_effect = RuntimeError("LLM error")

        result = await semantic_evaluate_risk(
            "Deploy API",
            50,
            mock_model,
            config=SemanticRiskConfig(cache_enabled=False),
        )
        # Should return medium risk with zero confidence (triggers keyword fallback)
        assert result.risk_level == "medium"
        assert result.confidence == 0.0
        assert result.requires_confirmation is True

    async def test_context_passed_to_prompt(self) -> None:
        """Context (workspace) should be included in risk prompt."""
        mock_model = MagicMock()
        assessment = RiskAssessment(risk_level="low", confidence=0.9)
        structured = MagicMock()
        structured.ainvoke = AsyncMock(return_value=assessment)
        mock_model.with_structured_output = MagicMock(return_value=structured)

        await semantic_evaluate_risk(
            "Read config file",
            50,
            mock_model,
            config=SemanticRiskConfig(cache_enabled=False),
            context="Workspace: /home/user/project",
        )
        # Verify the prompt included context
        call_args = structured.ainvoke.call_args
        messages = call_args[0][0]  # First positional arg is messages list
        prompt = messages[0].content  # First HumanMessage content
        assert "Workspace: /home/user/project" in prompt


@pytest.mark.asyncio
class TestEvaluateCriticalitySemantic:
    async def test_keyword_fallback_on_llm_failure(self) -> None:
        """When LLM fails, should use keyword-based fallback."""
        clear_risk_cache()
        mock_model = MagicMock()
        mock_model.with_structured_output = MagicMock(side_effect=RuntimeError("LLM error"))

        result = await evaluate_criticality_semantic(
            "Deploy the new API endpoint",  # Contains "deploy" keyword
            50,
            model=mock_model,
            config=SemanticRiskConfig(cache_enabled=False),
        )
        # Keyword fallback should catch "deploy" → should level
        assert result.level in ("must", "should")
        assert result.requires_confirmation is True

    async def test_low_confidence_uses_keywords(self) -> None:
        """Low confidence assessment should fall back to keywords."""
        clear_risk_cache()
        mock_model = MagicMock()
        assessment = RiskAssessment(
            risk_level="low",
            confidence=0.3,  # Below threshold
            reasoning="Uncertain",
        )
        structured = MagicMock()
        structured.ainvoke = AsyncMock(return_value=assessment)
        mock_model.with_structured_output = MagicMock(return_value=structured)

        result = await evaluate_criticality_semantic(
            "Deploy production database",  # Contains risky keywords
            50,
            model=mock_model,
            config=SemanticRiskConfig(
                cache_enabled=False,
                confidence_threshold=0.5,
            ),
        )
        # Low confidence → keyword fallback → should/must (deploy keyword)
        assert result.level in ("must", "should")

    async def test_disabled_uses_keyword_path(self) -> None:
        result = await evaluate_criticality_semantic(
            "Deploy the new API endpoint",
            50,
            model=None,
            config=SemanticRiskConfig(enabled=False),
        )
        assert result.level == "should"

    async def test_context_propagated(self) -> None:
        """Context should be passed through to risk evaluation."""
        clear_risk_cache()
        mock_model = MagicMock()
        assessment = RiskAssessment(risk_level="low", confidence=0.9)
        structured = MagicMock()
        structured.ainvoke = AsyncMock(return_value=assessment)
        mock_model.with_structured_output = MagicMock(return_value=structured)

        result = await evaluate_criticality_semantic(
            "Read documentation",
            50,
            model=mock_model,
            config=SemanticRiskConfig(cache_enabled=False),
            context="Workspace: /safe/local/path",
        )
        # Should complete successfully with context passed
        assert result.level == "nice"
