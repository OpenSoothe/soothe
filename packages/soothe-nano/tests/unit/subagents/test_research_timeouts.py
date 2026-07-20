"""Tests for research gather timeout alignment with wizsearch."""

from __future__ import annotations

from types import SimpleNamespace

from soothe_nano.subagents._research_timeouts import effective_source_timeout_sec
from soothe_nano.subagents.deep_research.protocol import DeepResearchConfig


def test_effective_source_timeout_covers_default_wizsearch() -> None:
    # Legacy default 10s must not cancel wizsearch's 30s inner timeout.
    assert effective_source_timeout_sec(10.0) == 35.0
    assert effective_source_timeout_sec(45.0) == 45.0


def test_effective_source_timeout_respects_config_wizsearch() -> None:
    cfg = SimpleNamespace(tools=SimpleNamespace(wizsearch=SimpleNamespace(timeout=60)))
    assert effective_source_timeout_sec(45.0, cfg) == 65.0


def test_deep_research_default_source_timeout() -> None:
    assert DeepResearchConfig().source_timeout_sec == 45.0
