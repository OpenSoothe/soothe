"""Tests for deep_research effort levels."""

from __future__ import annotations

from soothe_nano.subagents.deep_research.effort import (
    normalize_effort,
    parse_effort_from_text,
    profile_for_effort,
    resolve_effort,
)
from soothe_nano.subagents.deep_research.protocol import DeepResearchConfig


class TestEffortParsing:
    def test_parse_effort_from_topic(self) -> None:
        assert parse_effort_from_text("effort: thorough\nCompare vector DBs") == "thorough"
        assert parse_effort_from_text("Research effort=thorough on LLM agents") == "thorough"

    def test_parse_effort_missing(self) -> None:
        assert parse_effort_from_text("plain topic") is None

    def test_normalize_invalid(self) -> None:
        assert normalize_effort("bogus") == "normal"


class TestEffortProfiles:
    def test_normal_profile(self) -> None:
        p = profile_for_effort("normal")
        assert p.max_loops == 2
        assert p.crawl_top_n == 3

    def test_thorough_profile(self) -> None:
        p = profile_for_effort("thorough")
        assert p.max_loops == 4
        assert p.max_initial_queries == 8


class TestResolveEffort:
    def test_config_default_normal(self) -> None:
        effort, profile = resolve_effort(DeepResearchConfig())
        assert effort == "normal"
        assert profile.max_loops == 2

    def test_topic_overrides_config(self) -> None:
        cfg = DeepResearchConfig(effort="normal")
        effort, profile = resolve_effort(cfg, topic="effort: thorough\nTopic here")
        assert effort == "thorough"
        assert profile.max_loops == 4

    def test_context_max_loops_override(self) -> None:
        effort, profile = resolve_effort(
            DeepResearchConfig(effort="normal"),
            context_max_loops=7,
        )
        assert effort == "normal"
        assert profile.max_loops == 7
