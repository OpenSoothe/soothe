"""Dynamic periodic DAG health LLM gating (IG-743)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from soothe.autopilot.monitor import AutopilotMonitor
from soothe.autopilot.monitor.models import DagHealthReport
from soothe.config import SootheConfig
from soothe.context import ContextEngine
from soothe.events.internal_bus import InternalEventBus


def _make_monitor(
    ce: ContextEngine | None = None,
    *,
    config: SootheConfig | None = None,
) -> AutopilotMonitor:
    ce = ce or ContextEngine()
    bus = InternalEventBus()
    config = config or SootheConfig()
    with patch.object(SootheConfig, "create_chat_model", return_value=MagicMock()):
        return AutopilotMonitor(ce=ce, bus=bus, config=config)


@pytest.mark.asyncio
async def test_empty_dag_skips_health_llm() -> None:
    monitor = _make_monitor()
    reasoner = monitor._verifier._reasoner
    reasoner.verify_health = AsyncMock()  # type: ignore[method-assign]
    monitor._verifier.apply_health_report = AsyncMock()  # type: ignore[method-assign]

    await monitor._run_health_tick()

    reasoner.verify_health.assert_not_awaited()
    monitor._verifier.apply_health_report.assert_awaited_once()
    assert monitor._last_health_llm_fingerprint is None


@pytest.mark.asyncio
async def test_all_terminal_skips_health_llm() -> None:
    ce = ContextEngine()
    g = await ce.create_goal("done work", priority=50)
    await ce.complete_goal(g.id)
    monitor = _make_monitor(ce)
    reasoner = monitor._verifier._reasoner
    reasoner.verify_health = AsyncMock()  # type: ignore[method-assign]
    monitor._verifier.apply_health_report = AsyncMock()  # type: ignore[method-assign]

    await monitor._run_health_tick()

    reasoner.verify_health.assert_not_awaited()


@pytest.mark.asyncio
async def test_pending_goal_calls_health_llm() -> None:
    ce = ContextEngine()
    await ce.create_goal("open work", priority=50)
    monitor = _make_monitor(ce)
    reasoner = monitor._verifier._reasoner
    reasoner.verify_health = AsyncMock(  # type: ignore[method-assign]
        return_value=MagicMock(
            reset_goals=[],
            remove_goals=[],
            merge_goals=[],
            decompose_goals=[],
            priority_adjustments={},
            wire_dependencies=[],
            reasoning="ok",
        )
    )
    monitor._verifier.apply_health_report = AsyncMock()  # type: ignore[method-assign]

    await monitor._run_health_tick()

    reasoner.verify_health.assert_awaited_once()
    assert monitor._last_health_llm_fingerprint is not None


@pytest.mark.asyncio
async def test_debounce_skips_repeat_llm_on_unchanged_fingerprint() -> None:
    ce = ContextEngine()
    await ce.create_goal("open work", priority=50)
    monitor = _make_monitor(ce)
    reasoner = monitor._verifier._reasoner
    reasoner.verify_health = AsyncMock(  # type: ignore[method-assign]
        return_value=MagicMock(
            reset_goals=[],
            remove_goals=[],
            merge_goals=[],
            decompose_goals=[],
            priority_adjustments={},
            wire_dependencies=[],
            reasoning="ok",
        )
    )
    monitor._verifier.apply_health_report = AsyncMock()  # type: ignore[method-assign]

    await monitor._run_health_tick()
    await monitor._run_health_tick()

    assert reasoner.verify_health.await_count == 1


@pytest.mark.asyncio
async def test_verify_llm_disabled_skips_even_with_pending() -> None:
    cfg = SootheConfig()
    cfg.agent.autopilot.verify_llm_enabled = False
    ce = ContextEngine()
    await ce.create_goal("open work", priority=50)
    monitor = _make_monitor(ce, config=cfg)
    reasoner = monitor._verifier._reasoner
    reasoner.verify_health = AsyncMock()  # type: ignore[method-assign]
    monitor._verifier.apply_health_report = AsyncMock()  # type: ignore[method-assign]

    await monitor._run_health_tick()

    reasoner.verify_health.assert_not_awaited()


def test_verify_tick_interval_idle_vs_active() -> None:
    cfg = SootheConfig()
    cfg.agent.autopilot.verify_interval = 30
    cfg.agent.autopilot.verify_idle_interval = 300
    monitor = _make_monitor(config=cfg)

    assert monitor._verify_tick_interval(has_open_work=True) == 30.0
    assert monitor._verify_tick_interval(has_open_work=False) == 300.0


def test_verify_idle_interval_zero_reuses_active() -> None:
    cfg = SootheConfig()
    cfg.agent.autopilot.verify_interval = 45
    cfg.agent.autopilot.verify_idle_interval = 0
    monitor = _make_monitor(config=cfg)

    assert monitor._verify_tick_interval(has_open_work=False) == 45.0


def test_autopilot_config_defaults_for_dynamic_health() -> None:
    from soothe.config.models import AutopilotConfig

    ap = AutopilotConfig()
    assert ap.verify_periodic_enabled is False
    assert ap.verify_interval == 120
    assert ap.verify_idle_interval == 300
    assert ap.verify_llm_enabled is True
    assert ap.verify_llm_min_nonterminal == 1
    assert ap.verify_llm_debounce is True


@pytest.mark.asyncio
async def test_periodic_disabled_skips_health_tick() -> None:
    """Master switch off → health tick no-ops even with pending goals."""
    cfg = SootheConfig()
    assert cfg.agent.autopilot.verify_periodic_enabled is False
    ce = ContextEngine()
    await ce.create_goal("open work", priority=50)
    monitor = _make_monitor(ce, config=cfg)
    reasoner = monitor._verifier._reasoner
    reasoner.verify_health = AsyncMock()  # type: ignore[method-assign]
    monitor._verifier.apply_health_report = AsyncMock()  # type: ignore[method-assign]

    ran = await monitor._run_health_tick_if_enabled()

    assert ran is False
    reasoner.verify_health.assert_not_awaited()
    monitor._verifier.apply_health_report.assert_not_awaited()


@pytest.mark.asyncio
async def test_periodic_enabled_runs_health_tick() -> None:
    """Master switch on → health tick runs (LLM gated by remaining sub-knobs)."""
    cfg = SootheConfig()
    cfg.agent.autopilot.verify_periodic_enabled = True
    ce = ContextEngine()
    await ce.create_goal("open work", priority=50)
    monitor = _make_monitor(ce, config=cfg)
    reasoner = monitor._verifier._reasoner
    reasoner.verify_health = AsyncMock(  # type: ignore[method-assign]
        return_value=MagicMock(
            reset_goals=[],
            remove_goals=[],
            merge_goals=[],
            decompose_goals=[],
            priority_adjustments={},
            wire_dependencies=[],
            reasoning="ok",
        )
    )
    monitor._verifier.apply_health_report = AsyncMock()  # type: ignore[method-assign]

    ran = await monitor._run_health_tick_if_enabled()

    assert ran is True
    reasoner.verify_health.assert_awaited_once()


@pytest.mark.asyncio
async def test_verify_dag_health_use_llm_false_skips_reasoner() -> None:
    ce = ContextEngine()
    await ce.create_goal("open work", priority=50)
    monitor = _make_monitor(ce)
    reasoner = monitor._verifier._reasoner
    reasoner.verify_health = AsyncMock()  # type: ignore[method-assign]

    report = await monitor._verifier.verify_dag_health(use_llm=False)

    reasoner.verify_health.assert_not_awaited()
    assert isinstance(report, DagHealthReport)
    assert "LLM skipped" in report.reasoning
