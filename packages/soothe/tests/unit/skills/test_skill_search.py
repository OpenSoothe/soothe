"""Tests for unified deferred skill search (IG-543 P1/P2)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langchain_core.messages import HumanMessage

from soothe.config import SootheConfig
from soothe.foundation.skillify.models import SkillBundle, SkillRecord, SkillSearchResult
from soothe.middleware.skill_activation import SkillActivationMiddleware
from soothe.skills.index import SkillIndexEntry
from soothe.skills.registry import ProgressiveSkillRegistry
from soothe.skills.search import (
    merge_search_results,
    prefetch_core_skills_from_corpus,
    search_deferred_skills,
)


def _entry(name: str, *, source: str = "user") -> SkillIndexEntry:
    return SkillIndexEntry(
        name=name,
        description=f"{name} description",
        tags=name,
        source=source,
        path="/tmp",
        mtime=0.0,
    )


class TestMergeSearchResults:
    def test_substring_priority_then_semantic_score(self) -> None:
        substring = [_entry("alpha")]
        semantic = [
            (0.9, _entry("beta")),
            (0.95, _entry("gamma")),
        ]
        merged = merge_search_results(substring, semantic, limit=3)
        assert [entry.name for entry in merged] == ["alpha", "gamma", "beta"]

    def test_dedupes_by_name(self) -> None:
        substring = [_entry("alpha")]
        semantic = [(0.9, _entry("alpha"))]
        merged = merge_search_results(substring, semantic, limit=3)
        assert [entry.name for entry in merged] == ["alpha"]


class TestSemanticSearch:
    @pytest.mark.asyncio
    async def test_supplements_substring_when_enabled(self) -> None:
        registry = ProgressiveSkillRegistry()
        deferred = [_entry("db-migrate"), _entry("vector-only")]
        config = SootheConfig()
        config.progressive_skills.semantic_search_enabled = True
        config.progressive_skills.semantic_search_min_score = 0.0

        record = SkillRecord(
            id="vector-only",
            name="vector-only",
            description="semantic hit",
            path="/tmp/vector-only",
            tags=["ops"],
        )
        bundle = SkillBundle(
            query="deploy database",
            results=[SkillSearchResult(record=record, score=0.88)],
        )
        mock_service = MagicMock()
        mock_service.retrieve = AsyncMock(return_value=bundle)

        with patch(
            "soothe.foundation.skillify.start_skillify_service",
            return_value=mock_service,
        ):
            matches = await search_deferred_skills(
                "deploy",
                deferred,
                discovered=set(),
                limit=5,
                registry=registry,
                config=config,
                catalog_by_name={entry.name: entry for entry in deferred},
            )

        names = [entry.name for entry in matches]
        assert "vector-only" in names

    @pytest.mark.asyncio
    async def test_semantic_hits_outside_search_corpus_are_ignored(self) -> None:
        registry = ProgressiveSkillRegistry()
        core_weather = SkillIndexEntry(
            name="weather",
            description="Get current weather and forecasts",
            tags="weather, 天气, forecast",
            source="builtin",
            path="/tmp/weather",
            mtime=0.0,
        )
        deferred_only = _entry("platonic-coding")
        config = SootheConfig()
        config.progressive_skills.semantic_search_enabled = True
        config.progressive_skills.semantic_search_min_score = 0.0

        record = SkillRecord(
            id="platonic-coding",
            name="platonic-coding",
            description="spec-driven development lifecycle",
            path="/tmp/platonic-coding",
            tags=["workflow"],
        )
        bundle = SkillBundle(
            query="北京今天的天气",
            results=[SkillSearchResult(record=record, score=0.92)],
        )
        mock_service = MagicMock()
        mock_service.retrieve = AsyncMock(return_value=bundle)

        catalog = {core_weather.name: core_weather, deferred_only.name: deferred_only}
        with patch(
            "soothe.foundation.skillify.start_skillify_service",
            return_value=mock_service,
        ):
            matches = await search_deferred_skills(
                "北京今天的天气",
                [core_weather],
                discovered=set(),
                limit=2,
                registry=registry,
                config=config,
                catalog_by_name=catalog,
            )

        assert [entry.name for entry in matches] == ["weather"]

    def test_prefetch_core_corpus_excludes_semantic_only_hits(self) -> None:
        registry = ProgressiveSkillRegistry()
        weather = SkillIndexEntry(
            name="weather",
            description="Get current weather and forecasts",
            tags="weather, 天气, forecast",
            source="builtin",
            path="/tmp/weather",
            mtime=0.0,
        )
        github = SkillIndexEntry(
            name="github",
            description="GitHub CLI",
            tags="github, pull request",
            source="builtin",
            path="/tmp/github",
            mtime=0.0,
        )
        matches = prefetch_core_skills_from_corpus(
            "北京今天的天气",
            [weather, github],
            discovered=set(),
            limit=2,
            registry=registry,
        )
        assert [entry.name for entry in matches] == ["weather"]

    def test_prefetch_core_clawhub_from_spaced_query(self) -> None:
        registry = ProgressiveSkillRegistry()
        clawhub = SkillIndexEntry(
            name="clawhub",
            description="Search ClawHub registry",
            tags="clawhub, claw hub, skill registry",
            source="builtin",
            path="/tmp/clawhub",
            mtime=0.0,
        )
        weather = SkillIndexEntry(
            name="weather",
            description="Get current weather and forecasts",
            tags="weather, 天气, forecast",
            source="builtin",
            path="/tmp/weather",
            mtime=0.0,
        )
        matches = prefetch_core_skills_from_corpus(
            "is there skill of drawio on claw hub",
            [weather, clawhub],
            discovered=set(),
            limit=2,
            registry=registry,
        )
        assert [entry.name for entry in matches] == ["clawhub"]

    @pytest.mark.asyncio
    async def test_skips_semantic_when_disabled(self) -> None:
        registry = ProgressiveSkillRegistry()
        deferred = [_entry("vector-only")]
        config = MagicMock()
        config.progressive_skills.semantic_search_enabled = False

        with patch("soothe.foundation.skillify.start_skillify_service") as mock_get:
            matches = await search_deferred_skills(
                "vector-only",
                deferred,
                discovered=set(),
                limit=5,
                registry=registry,
                config=config,
                catalog_by_name={entry.name: entry for entry in deferred},
            )

        mock_get.assert_not_called()
        assert len(matches) == 1
        assert matches[0].name == "vector-only"

    @pytest.mark.asyncio
    async def test_falls_back_to_substring_when_embedding_service_unavailable(self) -> None:
        registry = ProgressiveSkillRegistry()
        deferred = [_entry("vector-only")]
        config = SootheConfig()
        config.progressive_skills.semantic_search_enabled = True

        mock_service = MagicMock()
        mock_service.retrieve = AsyncMock(
            return_value=SkillBundle(
                query=(
                    "[Embedding unavailable] Semantic skill search is temporarily unavailable. "
                    "Falling back to keyword matching."
                ),
                results=[],
            )
        )

        with patch(
            "soothe.foundation.skillify.start_skillify_service",
            return_value=mock_service,
        ):
            matches = await search_deferred_skills(
                "vector-only",
                deferred,
                discovered=set(),
                limit=5,
                registry=registry,
                config=config,
                catalog_by_name={entry.name: entry for entry in deferred},
            )

        assert len(matches) == 1
        assert matches[0].name == "vector-only"


class TestIntentPrefetch:
    @pytest.fixture
    def middleware(self) -> SkillActivationMiddleware:
        config = MagicMock()
        config.progressive_skills.core_skills = None
        config.progressive_skills.intent_prefetch_enabled = True
        config.progressive_skills.core_intent_auto_invoke_enabled = True
        config.progressive_skills.intent_prefetch_top_k = 2
        config.progressive_skills.intent_prefetch_min_query_chars = 4
        config.progressive_skills.semantic_search_enabled = False
        config.subagents = {}
        return SkillActivationMiddleware(
            registry=ProgressiveSkillRegistry(),
            catalog_provider=lambda: [
                SkillIndexEntry(
                    name="weather",
                    description="Get current weather and forecasts",
                    tags="weather, 天气, forecast",
                    source="builtin",
                    path="/tmp/weather",
                    mtime=0.0,
                ),
                _entry("db-migrate"),
            ],
            config=config,
        )

    @pytest.mark.asyncio
    async def test_prefetch_discovers_from_first_user_message(
        self,
        middleware: SkillActivationMiddleware,
    ) -> None:
        state = {
            "messages": [
                HumanMessage(content="Please run db-migrate for the staging database"),
            ],
        }

        result = await middleware.abefore_agent(state, None)

        assert result is not None
        activation = result["skill_activation"]
        assert activation["intent_prefetched"] is True
        assert "db-migrate" in activation["activated"]

    @pytest.mark.asyncio
    async def test_prefetch_runs_once(self, middleware: SkillActivationMiddleware) -> None:
        state = {
            "skill_activation": {
                **ProgressiveSkillRegistry.init_activation_state(),
                "intent_prefetched": True,
            },
            "messages": [HumanMessage(content="db-migrate staging please")],
        }

        result = await middleware.abefore_agent(state, None)

        assert result is None

    @pytest.mark.asyncio
    async def test_prefetch_auto_invokes_core_weather_from_chinese_query(
        self,
        middleware: SkillActivationMiddleware,
    ) -> None:
        state = {
            "messages": [HumanMessage(content="上海今天的天气")],
        }

        with patch(
            "soothe.middleware.skill_activation.SkillActivationMiddleware._invoke_skill_into_activation",
            return_value="weather",
        ) as mock_invoke:
            result = await middleware.abefore_agent(state, None)

        assert result is not None
        activation = result["skill_activation"]
        assert activation["intent_prefetched"] is True
        mock_invoke.assert_called_once()
        assert mock_invoke.call_args.args[1] == "weather"
        assert mock_invoke.call_args.kwargs.get("preload") is True

    @pytest.mark.asyncio
    async def test_prefetch_skips_deferred_when_core_corpus_matches(
        self,
        middleware: SkillActivationMiddleware,
    ) -> None:
        config = middleware._config
        config.progressive_skills.intent_prefetch_enabled = True
        config.progressive_skills.core_intent_auto_invoke_enabled = True
        config.progressive_skills.intent_prefetch_top_k = 2
        config.progressive_skills.intent_prefetch_min_query_chars = 4
        config.progressive_skills.semantic_search_enabled = True

        middleware._catalog_provider = lambda: [
            SkillIndexEntry(
                name="clawhub",
                description="Search ClawHub registry",
                tags="clawhub, claw hub",
                source="builtin",
                path="/tmp/clawhub",
                mtime=0.0,
            ),
            _entry("find-skills"),
            _entry("platonic-coding"),
        ]

        state = {
            "messages": [
                HumanMessage(content="is there skill of drawio on claw hub"),
            ],
        }

        with patch(
            "soothe.middleware.skill_activation.SkillActivationMiddleware._invoke_skill_into_activation",
            return_value="clawhub",
        ) as mock_invoke:
            with patch(
                "soothe.middleware.skill_activation.prefetch_deferred_skills",
                new_callable=AsyncMock,
            ) as mock_deferred:
                result = await middleware.abefore_agent(state, None)

        assert result is not None
        mock_invoke.assert_called_once()
        mock_deferred.assert_not_awaited()
        activation = result["skill_activation"]
        assert activation["intent_prefetched"] is True
