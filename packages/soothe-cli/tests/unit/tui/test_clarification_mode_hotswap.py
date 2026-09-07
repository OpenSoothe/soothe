"""Tests for the Shift+Tab agent-mode hot-swap RPC payload.

Covers the composer-mode cycle → `loop_set_clarification_mode` wire mapping:
auto/manual push `interaction_mode=None`; bypass pushes
`interaction_mode="bypass"` so the daemon swaps the live CoreAgent graph;
plan/ask do not push (next-turn-only).
"""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import patch

from soothe_cli.tui.app._messages_mixin import _MessagesMixin


class _FakeStatusBar:
    def __init__(self) -> None:
        self.last_mode: str | None = None

    def set_clarification_mode(self, mode: str) -> None:
        self.last_mode = mode


class _FakeSessionState:
    def __init__(self, loop_id: str) -> None:
        self.loop_id = loop_id


class _FakeDaemonSession:
    """Records `set_clarification_mode` calls (mode, interaction_mode)."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str | None]] = []

    async def set_clarification_mode(
        self,
        mode: str,
        *,
        interaction_mode: str | None = None,
    ) -> bool:
        self.calls.append((mode, interaction_mode))
        return True


class _CycleHarness(_MessagesMixin):
    """Harness that records pushes without running an event loop."""

    def __init__(self, *, initial: str = "auto") -> None:
        self._composer_mode = initial
        self._status_bar: Any = _FakeStatusBar()
        self.pushed: list[tuple[str, str | None]] = []

    def _push_clarification_mode_to_running_loop(
        self,
        mode: str,
        *,
        interaction_mode: str | None = None,
    ) -> None:
        self.pushed.append((mode, interaction_mode))


class _PushHarness(_MessagesMixin):
    """Harness carrying a fake session + loop id for the async push path."""

    def __init__(self, *, session: _FakeDaemonSession) -> None:
        self._composer_mode = "auto"
        self._status_bar: Any = _FakeStatusBar()
        self._daemon_session = session
        self._session_state = _FakeSessionState("loop-1")


def test_cycle_auto_to_bypass_pushes_bypass_interaction_mode() -> None:
    """Auto → Bypass pushes (mode=auto, interaction_mode=bypass)."""
    app = _CycleHarness(initial="auto")
    app.cycle_composer_mode()
    assert app._composer_mode == "bypass"
    assert app.pushed == [("auto", "bypass")]


def test_cycle_bypass_to_manual_pushs_default_graph() -> None:
    """Bypass → Manual pushes (mode=manual, interaction_mode=None).

    Switching off bypass back to the default graph re-gates mutating tools,
    so the daemon swaps the CoreAgent graph back to the interrupt-on variant.
    """
    app = _CycleHarness(initial="bypass")
    app.cycle_composer_mode()
    assert app._composer_mode == "manual"
    assert app.pushed == [("manual", None)]


def test_cycle_manual_to_auto_pushs_no_interaction_mode() -> None:
    """Manual → Auto pushes (mode=auto, interaction_mode=None)."""
    app = _CycleHarness(initial="manual")
    app.cycle_composer_mode()
    # Manual → Plan is next in the cycle; force auto via a full round trip.
    app._composer_mode = "ask"
    app.cycle_composer_mode()
    assert app._composer_mode == "auto"
    assert app.pushed == [("auto", None)]


def test_cycle_plan_does_not_push() -> None:
    """Plan is a standalone working mode; no hot-swap RPC fires."""
    app = _CycleHarness(initial="manual")
    app.cycle_composer_mode()
    assert app._composer_mode == "plan"
    assert app.pushed == []


def test_cycle_ask_does_not_push() -> None:
    """Ask is a standalone working mode; no hot-swap RPC fires."""
    app = _CycleHarness(initial="plan")
    app.cycle_composer_mode()
    assert app._composer_mode == "ask"
    assert app.pushed == []


def test_push_sends_interaction_mode_to_session() -> None:
    """`_push_clarification_mode_to_running_loop` forwards both fields."""
    session = _FakeDaemonSession()
    app = _PushHarness(session=session)

    async def _drive() -> None:
        # `get_event_loop()` inside a running loop returns this loop, so the
        # best-effort `create_task` lands here; yield twice to let it run.
        app._push_clarification_mode_to_running_loop("auto", interaction_mode="bypass")
        await asyncio.sleep(0)
        await asyncio.sleep(0)

    asyncio.run(_drive())
    assert session.calls == [("auto", "bypass")]


def test_push_omits_interaction_mode_when_none() -> None:
    """When interaction_mode is None the RPC payload omits the field."""
    session = _FakeDaemonSession()
    app = _PushHarness(session=session)

    async def _drive() -> None:
        app._push_clarification_mode_to_running_loop("manual")
        await asyncio.sleep(0)
        await asyncio.sleep(0)

    asyncio.run(_drive())
    assert session.calls == [("manual", None)]


def test_push_without_session_is_noop() -> None:
    """No daemon session → push silently does nothing (badge still flips)."""
    app = _CycleHarness(initial="auto")
    app._status_bar = None
    app._daemon_session = None  # type: ignore[attr-defined]
    # Should not raise.
    app._push_clarification_mode_to_running_loop("auto", interaction_mode="bypass")


def test_cycle_uses_resolve_composer_wire_fields() -> None:
    """Bypass wire fields come from `resolve_composer_wire_fields`, not a literal.

    Guards against hardcoding `interaction_mode="bypass"` in the cycle path.
    """

    class _Wire:
        clarification_mode = "auto"
        preferred_subagent: str | None = None
        interaction_mode = "bypass"

    with patch(
        "soothe_cli.tui.composer_mode.resolve_composer_wire_fields",
        return_value=_Wire(),
    ) as mocked:
        app = _CycleHarness(initial="auto")
        app.cycle_composer_mode()
        assert mocked.called
        assert mocked.call_args.args[0] == "bypass"
        # the cycle forwarded the wire field's interaction_mode, not a literal
        assert app.pushed == [("auto", "bypass")]
