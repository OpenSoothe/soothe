"""Tests for goaling tool group gating on autopilot."""

from __future__ import annotations

from soothe.config import SootheConfig
from soothe.runner.resolver._resolver_tools import _goaling_tools_enabled, resolve_tools


def test_goaling_disabled_without_autopilot() -> None:
    cfg = SootheConfig()
    cfg.agent.autonomous.enabled = False
    assert _goaling_tools_enabled(cfg) is False

    names = {t.name for t in resolve_tools(cfg.tools, config=cfg)}
    assert "suggest_goal" not in names
    assert "add_finding" not in names


def test_goaling_enabled_when_autopilot_on() -> None:
    cfg = SootheConfig()
    cfg.agent.autonomous.enabled = True

    assert _goaling_tools_enabled(cfg) is True

    names = {t.name for t in resolve_tools(cfg.tools, config=cfg)}
    assert "suggest_goal" in names
    assert "add_finding" in names


def test_goaling_default_autopilot_off() -> None:
    cfg = SootheConfig()
    assert cfg.agent.autonomous.enabled is False
    assert _goaling_tools_enabled(cfg) is False
