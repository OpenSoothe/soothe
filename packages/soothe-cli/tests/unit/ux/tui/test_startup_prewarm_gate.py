"""Tests for TUI startup prewarm gating before post-paint init."""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock

import pytest

from soothe_cli.tui.app._startup import _StartupMixin


class _StartupProbe(_StartupMixin):
    """Minimal object exposing startup hooks for unit tests."""

    def __init__(self) -> None:
        self._status_bar = MagicMock()
        self.call_after_refresh = MagicMock(return_value=True)


@pytest.mark.asyncio
async def test_deferred_startup_waits_for_prewarm_before_post_paint(monkeypatch) -> None:
    """Post-paint init must not run until import prewarm completes."""
    order: list[str] = []
    prewarm_started = asyncio.Event()
    prewarm_release = asyncio.Event()

    probe = _StartupProbe()

    def slow_prewarm() -> None:
        order.append("prewarm_start")
        prewarm_started.set()

    async def fake_to_thread(fn, *args, **kwargs):  # noqa: ANN001
        assert fn is slow_prewarm
        fn()
        await prewarm_release.wait()
        order.append("prewarm_done")
        return None

    def fake_call_after_refresh(callback) -> bool:  # noqa: ANN001
        order.append("post_paint_scheduled")
        return True

    monkeypatch.setattr(probe, "_prewarm_deferred_imports", slow_prewarm)
    monkeypatch.setattr(asyncio, "to_thread", fake_to_thread)
    probe.call_after_refresh = fake_call_after_refresh

    task = asyncio.create_task(probe._run_deferred_startup())
    await asyncio.wait_for(prewarm_started.wait(), timeout=1.0)
    assert "post_paint_scheduled" not in order

    prewarm_release.set()
    await asyncio.wait_for(task, timeout=1.0)

    assert order.index("prewarm_start") < order.index("prewarm_done")
    assert order.index("prewarm_done") < order.index("post_paint_scheduled")
