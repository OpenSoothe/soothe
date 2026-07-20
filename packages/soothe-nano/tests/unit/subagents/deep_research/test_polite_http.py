"""Tests for shared url_crawl polite HTTP."""

from __future__ import annotations

from soothe_nano.toolkits.url_crawl.polite_http import RateLimitConfig


def test_rate_limit_config_defaults() -> None:
    cfg = RateLimitConfig()
    assert cfg.limits == {}
    assert cfg.multiplier == 1.0
