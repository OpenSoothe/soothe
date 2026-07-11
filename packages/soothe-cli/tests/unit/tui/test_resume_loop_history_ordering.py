"""Regression test for RFC-413 loop-switch resume ordering.

`_resume_loop_via_daemon` (called when the user picks a loop in `/resume`,
formerly `/loops`) must hydrate the historical transcript before starting
the live event consumer. Without this ordering the user sees an empty
screen until new events arrive.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from soothe_cli.tui.app import SootheApp


@pytest.mark.asyncio
async def test_resume_loop_via_daemon_loads_history_before_live_consumer() -> None:
    """`/resume` switch must paint history before subscribing to live events."""
    app = object.__new__(SootheApp)

    # Track invocation order across the three async/sync calls we care about.
    call_order: list[str] = []

    async def _fake_switch_loop(loop_id: str) -> dict[str, str]:
        call_order.append(f"switch_loop:{loop_id}")
        return {"type": "loop_started", "loop_id": loop_id}

    async def _fake_load_history(*, loop_id: str | None = None) -> None:
        call_order.append(f"load_history:{loop_id}")

    def _fake_run_worker(*_args: object, **_kwargs: object) -> None:
        call_order.append("run_worker")

    daemon_session = MagicMock()
    daemon_session.switch_loop = AsyncMock(side_effect=_fake_switch_loop)
    app._daemon_session = daemon_session
    app._session_state = SimpleNamespace(loop_id="old_loop")
    app._lc_loop_id = "old_loop"
    app._loop_switching = False
    app._chat_input = None
    app._pending_messages = []
    app._queued_widgets = []
    app._tokens_approximate = False

    app._clear_messages = AsyncMock()
    app._mount_message = AsyncMock()
    app._update_status = MagicMock()
    app._update_tokens = MagicMock()
    app._update_welcome_banner = MagicMock()
    app._clear_loop_model_override = MagicMock()
    app._load_loop_history = AsyncMock(side_effect=_fake_load_history)
    app._consume_daemon_events_background = MagicMock()
    app.run_worker = MagicMock(side_effect=_fake_run_worker)

    await app._resume_loop_via_daemon("new_loop")

    daemon_session.switch_loop.assert_awaited_once_with("new_loop")
    app._load_loop_history.assert_awaited_once_with(loop_id="new_loop")
    app.run_worker.assert_called_once()

    assert call_order == [
        "switch_loop:new_loop",
        "load_history:new_loop",
        "run_worker",
    ], f"Unexpected call order: {call_order}"
    assert app._session_state.loop_id == "new_loop"
    assert app._lc_loop_id == "new_loop"


@pytest.mark.asyncio
async def test_resume_loop_via_daemon_skips_when_already_on_target_loop() -> None:
    """No-op switch must not invoke switch_loop or _load_loop_history."""
    app = object.__new__(SootheApp)

    daemon_session = MagicMock()
    daemon_session.switch_loop = AsyncMock()
    app._daemon_session = daemon_session
    app._session_state = SimpleNamespace(loop_id="loop_abc")
    app._lc_loop_id = "loop_abc"
    app._loop_switching = False
    app._chat_input = None
    app._mount_message = AsyncMock()
    app._load_loop_history = AsyncMock()
    app.run_worker = MagicMock()

    await app._resume_loop_via_daemon("loop_abc")

    daemon_session.switch_loop.assert_not_awaited()
    app._load_loop_history.assert_not_awaited()
    app.run_worker.assert_not_called()
    app._mount_message.assert_awaited_once()


@pytest.mark.asyncio
async def test_resume_loop_via_daemon_rolls_back_on_switch_failure() -> None:
    """Error path must restore prior loop id and skip history load."""
    app = object.__new__(SootheApp)

    daemon_session = MagicMock()
    daemon_session.switch_loop = AsyncMock(
        return_value={"type": "error", "message": "loop switch failed"}
    )
    app._daemon_session = daemon_session
    app._session_state = SimpleNamespace(loop_id="prev_loop")
    app._lc_loop_id = "prev_loop"
    app._loop_switching = False
    app._chat_input = None
    app._pending_messages = []
    app._queued_widgets = []
    app._tokens_approximate = False

    app._clear_messages = AsyncMock()
    app._mount_message = AsyncMock()
    app._update_status = MagicMock()
    app._update_tokens = MagicMock()
    app._update_welcome_banner = MagicMock()
    app._clear_loop_model_override = MagicMock()
    app._load_loop_history = AsyncMock()
    app._consume_daemon_events_background = MagicMock()
    app.run_worker = MagicMock()

    await app._resume_loop_via_daemon("broken_loop")

    daemon_session.switch_loop.assert_awaited_once_with("broken_loop")
    app._load_loop_history.assert_not_awaited()
    app.run_worker.assert_not_called()
    assert app._session_state.loop_id == "prev_loop"
    assert app._lc_loop_id == "prev_loop"
