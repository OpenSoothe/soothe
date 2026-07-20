"""Tests for unified deferred skill search (substring / corpus matching)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langchain_core.messages import HumanMessage

from soothe_nano.middleware.skill_activation import SkillActivationMiddleware
from soothe_nano.skills.index import SkillIndexEntry
from soothe_nano.skills.registry import ProgressiveSkillRegistry
from soothe_nano.skills.search import (
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


class TestSubstringSearch:
    @pytest.mark.asyncio
    async def test_search_deferred_uses_substring_only(self) -> None:
        registry = ProgressiveSkillRegistry()
        deferred = [_entry("db-migrate"), _entry("vector-only")]
        matches = await search_deferred_skills(
            "deploy",
            deferred,
            discovered=set(),
            limit=5,
            registry=registry,
            config=MagicMock(),
            catalog_by_name={entry.name: entry for entry in deferred},
        )
        # "deploy" does not substring-match either name/description tag set here
        assert matches == []

    @pytest.mark.asyncio
    async def test_search_deferred_matches_by_name_substring(self) -> None:
        registry = ProgressiveSkillRegistry()
        deferred = [_entry("db-migrate"), _entry("vector-only")]
        matches = await search_deferred_skills(
            "migrate",
            deferred,
            discovered=set(),
            limit=5,
            registry=registry,
            config=MagicMock(),
            catalog_by_name={entry.name: entry for entry in deferred},
        )
        assert [entry.name for entry in matches] == ["db-migrate"]

    def test_prefetch_core_corpus_excludes_unrelated_skills(self) -> None:
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
            "soothe_nano.middleware.skill_activation.SkillActivationMiddleware._invoke_skill_into_activation",
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
            "soothe_nano.middleware.skill_activation.SkillActivationMiddleware._invoke_skill_into_activation",
            return_value="clawhub",
        ) as mock_invoke:
            with patch(
                "soothe_nano.middleware.skill_activation.prefetch_deferred_skills",
                new_callable=AsyncMock,
            ) as mock_deferred:
                result = await middleware.abefore_agent(state, None)

        assert result is not None
        mock_invoke.assert_called_once()
        mock_deferred.assert_not_awaited()
        activation = result["skill_activation"]
        assert activation["intent_prefetched"] is True
