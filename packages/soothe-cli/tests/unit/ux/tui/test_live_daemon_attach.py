"""Live-daemon attach: skip send_turn when a follow-on goal is already running."""

from __future__ import annotations

from collections import deque
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest

from soothe_cli.runtime.state.session_stats import SessionStats
from soothe_cli.tui.app._execution import _ExecutionMixin
from soothe_cli.tui.app._module_init import QueuedMessage


def _execution_app(*, live: bool = False) -> Any:  # noqa: ANN401
    app = object.__new__(_ExecutionMixin)
    app._ui_adapter = SimpleNamespace()
    app._daemon_session = SimpleNamespace(
        ensure_connected=AsyncMock(),
        fetch_loop_history=AsyncMock(
            return_value=SimpleNamespace(live_goal_index=0 if live else None)
        ),
        fetch_execution_state=AsyncMock(
            return_value=SimpleNamespace(status="running" if live else "idle")
        ),
    )
    app._assistant_id = "soothe"
    app._session_state = SimpleNamespace(loop_id="loop-1")
    app._image_tracker = None
    app._sandbox_type = None
    app._cwd = "/tmp"
    app._model_override = None
    app._model_params_override = None
    app._router_profile_override = None
    app._composer_mode = "auto"
    app._exit = False
    app._inflight_turn_stats = None
    app._inflight_turn_start = None
    app._session_stats = SessionStats()
    app._agent_running = False
    app._agent_worker = None
    app._shell_running = False
    app._pending_messages: deque[QueuedMessage] = deque()
    app._queued_widgets: deque[Any] = deque()
    app._mount_message = AsyncMock()
    app._send_to_agent = AsyncMock()
    app._process_next_from_queue = AsyncMock()
    app._process_message = AsyncMock()
    app._maybe_drain_deferred = AsyncMock()
    app._set_spinner = AsyncMock()
    app._refresh_token_displays = lambda **_kw: None
    app._tokens_approximate = False
    app._chat_input = None
    app._primary_text_input = lambda: None
    app.focus_primary_input = lambda: None
    app._runtime_backend_ready = lambda: True
    app._refresh_queued_goal_tips = lambda: None
    app._try_recover_goal_completion_from_ledger = AsyncMock()
    app._cleanup_agent_task = AsyncMock()
    return app


@pytest.mark.asyncio
async def test_daemon_loop_is_live_uses_live_goal_index() -> None:
    app = _execution_app(live=True)
    assert await app._daemon_loop_is_live() is True
    app._daemon_session.fetch_loop_history.return_value = SimpleNamespace(live_goal_index=None)
    app._daemon_session.fetch_execution_state.return_value = SimpleNamespace(status="idle")
    assert await app._daemon_loop_is_live() is False


@pytest.mark.asyncio
async def test_run_agent_task_forces_skip_when_live(monkeypatch: Any) -> None:  # noqa: ANN401
    app = _execution_app(live=True)
    captured: dict[str, Any] = {}

    async def fake_execute(**kwargs: Any) -> SessionStats:
        captured.update(kwargs)
        return SessionStats()

    monkeypatch.setattr("soothe_cli.tui.textual_adapter.execute_task_textual", fake_execute)

    await app._run_agent_task("also cleanse legacy", skip_daemon_send_turn=False)

    assert captured["skip_daemon_send_turn"] is True


@pytest.mark.asyncio
async def test_run_agent_task_sends_when_not_live(monkeypatch: Any) -> None:  # noqa: ANN401
    app = _execution_app(live=False)
    captured: dict[str, Any] = {}

    async def fake_execute(**kwargs: Any) -> SessionStats:
        captured.update(kwargs)
        return SessionStats()

    monkeypatch.setattr("soothe_cli.tui.textual_adapter.execute_task_textual", fake_execute)

    await app._run_agent_task("hello", skip_daemon_send_turn=False)

    assert captured["skip_daemon_send_turn"] is False


@pytest.mark.asyncio
async def test_cleanup_attaches_when_still_live() -> None:
    app = _execution_app(live=True)
    app._attach_to_live_daemon_turn = AsyncMock()

    await _ExecutionMixin._cleanup_agent_task(app)

    app._attach_to_live_daemon_turn.assert_awaited_once()
    app._process_next_from_queue.assert_not_awaited()


@pytest.mark.asyncio
async def test_cleanup_drains_queue_when_not_live() -> None:
    app = _execution_app(live=False)

    await _ExecutionMixin._cleanup_agent_task(app)

    app._process_next_from_queue.assert_awaited_once()


@pytest.mark.asyncio
async def test_attach_to_live_drains_queued_normal_message() -> None:
    app = _execution_app(live=True)
    app._pending_messages.append(QueuedMessage(text="follow-on goal", mode="normal"))
    queued = SimpleNamespace(remove=AsyncMock())
    app._queued_widgets.append(queued)

    await app._attach_to_live_daemon_turn()

    app._mount_message.assert_awaited()
    app._send_to_agent.assert_awaited_once_with(
        "follow-on goal",
        skip_daemon_send_turn=True,
    )
    assert not app._pending_messages


@pytest.mark.asyncio
async def test_attach_to_live_without_queue_uses_empty_prompt() -> None:
    app = _execution_app(live=True)

    await app._attach_to_live_daemon_turn()

    app._send_to_agent.assert_awaited_once_with("", skip_daemon_send_turn=True)
