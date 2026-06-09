"""Tests for semantic risk classifier (IG-433)."""

from typing import Any
from unittest.mock import MagicMock

import pytest

from soothe.config.models import SemanticRiskConfig
from soothe.foundation.autopilot.engine import semantic_risk_classifier as srm
from soothe.foundation.autopilot.engine.semantic_risk_classifier import (
    RiskAssessment,
    RiskCache,
    clear_risk_cache,
    evaluate_criticality_semantic,
    risk_assessment_to_criticality,
    semantic_evaluate_risk,
)


def _patch_typed(
    monkeypatch: pytest.MonkeyPatch,
    *,
    result: RiskAssessment | None = None,
    side_effect: Exception | None = None,
    capture: dict[str, Any] | None = None,
) -> None:
    async def _fake(_model: Any, messages: Any, _schema: type[Any], **_kwargs: Any) -> Any:
        if capture is not None:
            capture["messages"] = messages
        if side_effect is not None:
            raise side_effect
        return result

    monkeypatch.setattr(srm, "invoke_structured_chat_typed", _fake)


class TestRiskCache:
    def test_exact_match_returns_cached(self) -> None:
        cache = RiskCache()
        assessment = RiskAssessment(
            risk_level="high",
            confidence=0.9,
            reasoning="Cached assessment",
        )
        cache.store("Deploy production", [0.1, 0.2], assessment)

        result = cache.lookup_exact("Deploy production")
        assert result is not None
        assert result.risk_level == "high"

        result = cache.lookup_exact("Deploy staging")
        assert result is None

    def test_normalized_exact_match(self) -> None:
        cache = RiskCache()
        assessment = RiskAssessment(risk_level="low", confidence=0.9)
        cache.store("Deploy Test API", [0.1, 0.2], assessment)

        result = cache.lookup_exact("deploy test api")
        assert result is not None
        assert result.risk_level == "low"

    def test_lru_bounded(self) -> None:
        cache = RiskCache(max_entries=5)
        for i in range(10):
            cache.store(f"Goal {i}", [float(i)], RiskAssessment(risk_level="low"))
        assert len(cache.entries) == 5
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
    async def test_llm_structured_assessment(self, monkeypatch: pytest.MonkeyPatch) -> None:
        clear_risk_cache()
        assessment = RiskAssessment(
            risk_level="medium",
            confidence=0.8,
            reasoning="Touches external API",
            requires_confirmation=True,
        )
        _patch_typed(monkeypatch, result=assessment)

        result = await semantic_evaluate_risk(
            "Sync user profiles with CRM",
            50,
            MagicMock(),
            config=SemanticRiskConfig(cache_enabled=False),
        )
        assert result.risk_level == "medium"
        assert result.confidence >= 0.5

    async def test_exact_cache_hit(self, monkeypatch: pytest.MonkeyPatch) -> None:
        cache = RiskCache()
        cached_assessment = RiskAssessment(
            risk_level="high",
            confidence=0.9,
            reasoning="Cached",
        )
        cache.store("Deploy production database", [0.5, 0.5], cached_assessment)

        called: dict[str, bool] = {"hit": False}

        async def _should_not_be_called(*_args: Any, **_kwargs: Any) -> Any:
            called["hit"] = True
            raise AssertionError("LLM should not be invoked on cache hit")

        monkeypatch.setattr(srm, "invoke_structured_chat_typed", _should_not_be_called)

        result = await semantic_evaluate_risk(
            "Deploy production database",
            50,
            MagicMock(),
            config=SemanticRiskConfig(cache_enabled=True),
            cache=cache,
        )
        assert result.risk_level == "high"
        assert result.reasoning == "Cached"
        assert called["hit"] is False

    async def test_llm_failure_returns_low_confidence_fallback(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _patch_typed(monkeypatch, side_effect=RuntimeError("LLM error"))

        result = await semantic_evaluate_risk(
            "Deploy API",
            50,
            MagicMock(),
            config=SemanticRiskConfig(cache_enabled=False),
        )
        assert result.risk_level == "medium"
        assert result.confidence == 0.0
        assert result.requires_confirmation is True

    async def test_context_passed_to_prompt(self, monkeypatch: pytest.MonkeyPatch) -> None:
        capture: dict[str, Any] = {}
        _patch_typed(
            monkeypatch,
            result=RiskAssessment(risk_level="low", confidence=0.9),
            capture=capture,
        )

        await semantic_evaluate_risk(
            "Read config file",
            50,
            MagicMock(),
            config=SemanticRiskConfig(cache_enabled=False),
            context="Workspace: /home/user/project",
        )
        messages = capture["messages"]
        prompt = messages[0].content
        assert "Workspace: /home/user/project" in prompt


@pytest.mark.asyncio
class TestEvaluateCriticalitySemantic:
    async def test_keyword_fallback_on_llm_failure(self, monkeypatch: pytest.MonkeyPatch) -> None:
        clear_risk_cache()
        _patch_typed(monkeypatch, side_effect=RuntimeError("LLM error"))

        result = await evaluate_criticality_semantic(
            "Deploy the new API endpoint",
            50,
            model=MagicMock(),
            config=SemanticRiskConfig(cache_enabled=False),
        )
        assert result.level in ("must", "should")
        assert result.requires_confirmation is True

    async def test_low_confidence_uses_keywords(self, monkeypatch: pytest.MonkeyPatch) -> None:
        clear_risk_cache()
        _patch_typed(
            monkeypatch,
            result=RiskAssessment(
                risk_level="low",
                confidence=0.3,
                reasoning="Uncertain",
            ),
        )

        result = await evaluate_criticality_semantic(
            "Deploy production database",
            50,
            model=MagicMock(),
            config=SemanticRiskConfig(
                cache_enabled=False,
                confidence_threshold=0.5,
            ),
        )
        assert result.level in ("must", "should")

    async def test_disabled_uses_keyword_path(self) -> None:
        result = await evaluate_criticality_semantic(
            "Deploy the new API endpoint",
            50,
            model=None,
            config=SemanticRiskConfig(enabled=False),
        )
        assert result.level == "should"

    async def test_context_propagated(self, monkeypatch: pytest.MonkeyPatch) -> None:
        clear_risk_cache()
        _patch_typed(
            monkeypatch,
            result=RiskAssessment(risk_level="low", confidence=0.9),
        )

        result = await evaluate_criticality_semantic(
            "Read documentation",
            50,
            model=MagicMock(),
            config=SemanticRiskConfig(cache_enabled=False),
            context="Workspace: /safe/local/path",
        )
        assert result.level == "nice"
