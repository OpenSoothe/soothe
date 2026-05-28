"""Unit tests for paced assistant markdown rendering during hydration."""

from __future__ import annotations

from collections import deque
from typing import Any
from unittest.mock import AsyncMock

import pytest

from soothe_cli.tui.app._ui import _UIMixin


def _long_markdown() -> str:
    """Generate long markdown content representative of heavy hydration payloads."""
    bullets = "\n".join(f"- item {idx}" for idx in range(300))
    code = "\n".join("print('line')" for _ in range(120))
    return f"# Long report\n{bullets}\n```python\n{code}\n```"


class _FakeHydrationApp:
    """Minimal host object that provides fields used by `_UIMixin` queue methods."""

    def __init__(self) -> None:
        self._deferred_assistant_renders: deque[tuple[Any, str]] = deque()
        self._assistant_render_drain_scheduled = False
        self._assistant_render_drain_in_progress = False
        self.scheduled_callbacks: list[Any] = []

    def call_later(self, fn: Any) -> None:
        self.scheduled_callbacks.append(fn)


@pytest.mark.asyncio
async def test_enqueue_many_hydrated_messages_schedules_single_drain() -> None:
    app = _FakeHydrationApp()
    widget = type("Widget", (), {"is_attached": True, "set_content": AsyncMock()})()

    for _ in range(100):
        _UIMixin._enqueue_hydrated_assistant_render(app, widget, _long_markdown())

    assert len(app._deferred_assistant_renders) == 100
    assert app._assistant_render_drain_scheduled is True
    assert len(app.scheduled_callbacks) == 1
    widget.set_content.assert_not_awaited()


@pytest.mark.asyncio
async def test_drain_processes_at_most_two_messages_per_tick(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = _FakeHydrationApp()
    widgets = [
        type("Widget", (), {"is_attached": True, "set_content": AsyncMock()})() for _ in range(6)
    ]
    for widget in widgets:
        app._deferred_assistant_renders.append((widget, _long_markdown()))

    monkeypatch.setattr("soothe_cli.tui.app._ui._monotonic", lambda: 10.0)
    await _UIMixin._drain_hydrated_assistant_renders(app)

    widgets[0].set_content.assert_awaited_once()
    widgets[1].set_content.assert_awaited_once()
    for widget in widgets[2:]:
        widget.set_content.assert_not_awaited()
    assert len(app._deferred_assistant_renders) == 4
    assert app._assistant_render_drain_scheduled is True
    assert len(app.scheduled_callbacks) == 1


@pytest.mark.asyncio
async def test_drain_skips_detached_widgets_and_keeps_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = _FakeHydrationApp()
    detached = type("Widget", (), {"is_attached": False, "set_content": AsyncMock()})()
    active1 = type("Widget", (), {"is_attached": True, "set_content": AsyncMock()})()
    active2 = type("Widget", (), {"is_attached": True, "set_content": AsyncMock()})()
    active3 = type("Widget", (), {"is_attached": True, "set_content": AsyncMock()})()
    app._deferred_assistant_renders.extend(
        [
            (detached, _long_markdown()),
            (active1, _long_markdown()),
            (active2, _long_markdown()),
            (active3, _long_markdown()),
        ]
    )

    monkeypatch.setattr("soothe_cli.tui.app._ui._monotonic", lambda: 10.0)
    await _UIMixin._drain_hydrated_assistant_renders(app)

    detached.set_content.assert_not_awaited()
    active1.set_content.assert_awaited_once()
    active2.set_content.assert_awaited_once()
    active3.set_content.assert_not_awaited()
    assert len(app._deferred_assistant_renders) == 1
    assert app._assistant_render_drain_scheduled is True
