"""Tests for unified deferred skill search (IG-543 P1/P2)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langchain_core.messages import HumanMessage

from soothe.config import SootheConfig
from soothe.middleware.skill_activation import SkillActivationMiddleware
from soothe.skills.index import SkillIndexEntry
from soothe.skills.registry import ProgressiveSkillRegistry
from soothe.skills.search import (
    merge_search_results,
    search_deferred_skills,
)
from soothe.subagents.skillify.models import SkillBundle, SkillRecord, SkillSearchResult


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
        mock_retriever = AsyncMock()
        mock_retriever.retrieve.return_value = bundle

        with patch(
            "soothe.subagents.skillify.runtime.get_skillify_retriever",
            return_value=mock_retriever,
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
    async def test_skips_semantic_when_disabled(self) -> None:
        registry = ProgressiveSkillRegistry()
        deferred = [_entry("vector-only")]
        config = MagicMock()
        config.progressive_skills.semantic_search_enabled = False

        with patch("soothe.subagents.skillify.runtime.get_skillify_retriever") as mock_get:
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
