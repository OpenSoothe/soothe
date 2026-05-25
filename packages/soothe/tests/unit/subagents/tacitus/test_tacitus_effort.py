"""Tests for Tacitus effort levels."""

from __future__ import annotations

from soothe.subagents.tacitus.effort import (
    normalize_effort,
    parse_effort_from_text,
    profile_for_effort,
    resolve_effort,
)
from soothe.subagents.tacitus.protocol import TacitusConfig


class TestEffortParsing:
    def test_parse_effort_from_topic(self) -> None:
        assert parse_effort_from_text("effort: xhigh\nCompare vector DBs") == "xhigh"
        assert parse_effort_from_text("Research effort=high on LLM agents") == "high"

    def test_parse_effort_missing(self) -> None:
        assert parse_effort_from_text("plain topic") is None

    def test_normalize_invalid(self) -> None:
        assert normalize_effort("bogus") == "normal"


class TestEffortProfiles:
    def test_normal_profile(self) -> None:
        p = profile_for_effort("normal")
        assert p.max_loops == 2
        assert p.max_sub_questions == 3

    def test_xhigh_profile(self) -> None:
        p = profile_for_effort("xhigh")
        assert p.max_loops == 5
        assert p.max_initial_queries == 10


class TestResolveEffort:
    def test_config_default_normal(self) -> None:
        effort, profile = resolve_effort(TacitusConfig())
        assert effort == "normal"
        assert profile.max_loops == 2

    def test_topic_overrides_config(self) -> None:
        cfg = TacitusConfig(effort="normal")
        effort, profile = resolve_effort(cfg, topic="effort: high\nTopic here")
        assert effort == "high"
        assert profile.max_loops == 3

    def test_context_max_loops_override(self) -> None:
        effort, profile = resolve_effort(
            TacitusConfig(effort="normal"),
            context_max_loops=7,
        )
        assert effort == "normal"
        assert profile.max_loops == 7
