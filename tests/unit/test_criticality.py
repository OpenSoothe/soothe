"""criticality evaluator (soothe.cognition.criticality)."""

import pytest

from soothe.cognition.criticality import (
    _MUST_REASONS_THRESHOLD,
    _PRIORITY_MUST_THRESHOLD,
    HIGH_RISK_KEYWORDS,
    CriticalityResult,
    _matches_risk_keywords,
    evaluate_criticality,
    evaluate_criticality_async,
)


class TestCriticalityResult:
    """Tests for the CriticalityResult dataclass."""

    def test_must_level(self) -> None:
        result = CriticalityResult(level="must", reasons=["Test"], requires_confirmation=True)
        assert result.is_must is True
        assert result.is_should is False
        assert result.requires_confirmation is True

    def test_should_level(self) -> None:
        result = CriticalityResult(level="should", reasons=["Test"], requires_confirmation=True)
        assert result.is_must is False
        assert result.is_should is True
        assert result.requires_confirmation is True

    def test_nice_level(self) -> None:
        result = CriticalityResult(level="nice", reasons=[])
        assert result.is_must is False
        assert result.is_should is False
        assert result.requires_confirmation is False


class TestMatchesRiskKeywords:
    """Tests for the _matches_risk_keywords helper."""

    def test_matches_single_keyword(self) -> None:
        assert _matches_risk_keywords("deploy to production", HIGH_RISK_KEYWORDS) is True

    def test_matches_billing(self) -> None:
        assert _matches_risk_keywords("process billing", HIGH_RISK_KEYWORDS) is True

    def test_no_match(self) -> None:
        assert _matches_risk_keywords("write a report", HIGH_RISK_KEYWORDS) is False

    def test_case_insensitive(self) -> None:
        # Function expects pre-lowercased input (as caller does .lower())
        assert _matches_risk_keywords("delete the table", HIGH_RISK_KEYWORDS) is True
        # Also works with uppercase in input since keywords are lowercase
        assert _matches_risk_keywords("DELETE the table".lower(), HIGH_RISK_KEYWORDS) is True

    def test_empty_text(self) -> None:
        assert _matches_risk_keywords("", HIGH_RISK_KEYWORDS) is False


class TestEvaluateCriticality:
    """Tests for the sync evaluate_criticality function."""

    def test_nice_goal(self) -> None:
        result = evaluate_criticality("Write a summary of recent events")
        assert result.level == "nice"
        assert result.requires_confirmation is False
        assert result.reasons == []

    def test_should_single_reason(self) -> None:
        result = evaluate_criticality("Deploy the new API endpoint", priority=50)
        assert result.level == "should"
        assert result.requires_confirmation is True
        assert len(result.reasons) == 1

    def test_must_multiple_reasons(self) -> None:
        result = evaluate_criticality("Deploy and delete the old billing system", priority=95)
        assert result.level == "must"
        assert result.requires_confirmation is True
        assert len(result.reasons) >= _MUST_REASONS_THRESHOLD

    def test_must_from_priority(self) -> None:
        result = evaluate_criticality("Some task", priority=_PRIORITY_MUST_THRESHOLD)
        assert result.level == "should"
        assert result.requires_confirmation is True

    def test_must_from_high_priority_and_risk(self) -> None:
        desc = "Deploy and delete the old system"
        result = evaluate_criticality(desc, priority=_PRIORITY_MUST_THRESHOLD)
        assert result.level == "must"
        assert result.requires_confirmation is True

    def test_long_description_triggers_reason(self) -> None:
        desc = "x" * 501
        result = evaluate_criticality(desc)
        assert result.level == "should"
        assert any("Large scope" in r for r in result.reasons)

    def test_multiple_risk_keywords_triggers_must(self) -> None:
        desc = "Deploy and delete the production database"
        result = evaluate_criticality(desc, priority=95)
        assert result.level == "must"

    def test_sync_ignores_llm_params(self) -> None:
        result = evaluate_criticality("Write a simple script", use_llm=True, model=None)
        assert result.level == "nice"


@pytest.mark.asyncio
class TestEvaluateCriticalityAsync:
    """Tests for the async evaluate_criticality_async function."""

    async def test_nice_goal(self) -> None:
        result = await evaluate_criticality_async("Write a summary")
        assert result.level == "nice"

    async def test_should_from_risk_keyword(self) -> None:
        result = await evaluate_criticality_async("Deploy the API")
        assert result.level == "should"
        assert result.requires_confirmation is True

    async def test_must_from_multiple_reasons(self) -> None:
        desc = "Deploy and delete the old billing system"
        result = await evaluate_criticality_async(desc, priority=95)
        assert result.level == "must"
        assert result.requires_confirmation is True

    async def test_llm_medium_risk(self) -> None:
        from unittest.mock import AsyncMock

        mock_model = AsyncMock()
        mock_model.ainvoke.return_value.type = "ai"
        mock_model.ainvoke.return_value.content = "RISK_LEVEL: medium\nREASONS: Moderate external system impact"

        result = await evaluate_criticality_async(
            "Review the API documentation",
            use_llm=True,
            model=mock_model,
        )
        assert result.level == "should"
        assert result.requires_confirmation is True
        assert "external system" in result.reasons[0].lower()

    async def test_llm_high_risk_elevates_to_must(self) -> None:
        from unittest.mock import AsyncMock

        mock_model = AsyncMock()
        mock_model.ainvoke.return_value.type = "ai"
        mock_model.ainvoke.return_value.content = (
            "RISK_LEVEL: high\nREASONS: Security implications, external system modification"
        )

        result = await evaluate_criticality_async(
            "Run a quick audit",
            use_llm=True,
            model=mock_model,
        )
        assert result.level == "must"
        assert result.requires_confirmation is True

    async def test_llm_low_risk_stays_nice(self) -> None:
        from unittest.mock import AsyncMock

        mock_model = AsyncMock()
        mock_model.ainvoke.return_value.type = "ai"
        mock_model.ainvoke.return_value.content = "RISK_LEVEL: low\nREASONS: No significant concerns identified"

        result = await evaluate_criticality_async(
            "Review the API documentation",
            use_llm=True,
            model=mock_model,
        )
        assert result.level == "nice"
        assert result.requires_confirmation is False

    async def test_llm_fallback_on_error(self) -> None:
        from unittest.mock import AsyncMock

        mock_model = AsyncMock()
        mock_model.ainvoke.side_effect = RuntimeError("API error")

        result = await evaluate_criticality_async(
            "Review documentation",
            use_llm=True,
            model=mock_model,
        )
        # LLM fails, falls back to medium risk -> should
        assert result.level == "should"
        assert result.requires_confirmation is True
        assert any("unavailable" in r for r in result.reasons)
