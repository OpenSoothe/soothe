"""Reconnect retry for slash-skill turns must resend real content."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest

from soothe_cli.runtime.state.session_stats import SessionStats
from soothe_cli.tui.app._execution import _ExecutionMixin
from soothe_cli.tui.app._startup import _StartupMixin


def _startup_app(echo: dict[str, Any]) -> Any:  # noqa: ANN401  # Test stub app
    app = object.__new__(_StartupMixin)
    app._daemon_session = SimpleNamespace(invoke_skill=AsyncMock(return_value={"echo": echo}))
    app._agent_running = False
    app._shell_running = False
    app._clarification_mode = None
    app._mount_message = AsyncMock()
    app._send_to_agent = AsyncMock()
    return app


@pytest.mark.asyncio
async def test_skill_invocation_sends_queued_selector_line() -> None:
    app = _startup_app(
        {
            "skill_name": "omr-bootstrap",
            "description": "",
            "source": "",
            "body": "# Bootstrap",
            "args": "research on VL models",
        }
    )

    await app._invoke_skill_daemon(
        "/skill:omr-bootstrap research on VL models",
        "omr-bootstrap",
        "research on VL models",
    )

    app._send_to_agent.assert_awaited_once_with(
        "/skill:omr-bootstrap research on VL models",
        skip_daemon_send_turn=True,
    )


@pytest.mark.asyncio
async def test_skill_invocation_without_args_sends_bare_selector() -> None:
    app = _startup_app(
        {
            "skill_name": "omr-bootstrap",
            "description": "",
            "source": "",
            "body": "# Bootstrap",
            "args": "",
        }
    )

    await app._invoke_skill_daemon("/skill:omr-bootstrap", "omr-bootstrap", "")

    app._send_to_agent.assert_awaited_once_with(
        "/skill:omr-bootstrap",
        skip_daemon_send_turn=True,
    )


def _execution_app() -> Any:  # noqa: ANN401  # Test stub app
    app = object.__new__(_ExecutionMixin)
    app._ui_adapter = SimpleNamespace(
        finalize_pending_tools_with_error=lambda _msg: None,
        finalize_pending_steps_with_error=lambda _msg: None,
    )
    app._daemon_session = SimpleNamespace(ensure_connected=AsyncMock())
    app._assistant_id = "soothe"
    app._session_state = SimpleNamespace(loop_id="loop-1")
    app._image_tracker = None
    app._sandbox_type = None
    app._cwd = "/tmp"
    app._model_override = None
    app._model_params_override = None
    app._router_profile_override = None
    app._clarification_mode = None
    app._exit = False
    app._inflight_turn_stats = None
    app._inflight_turn_start = None
    app._session_stats = SessionStats()
    app._agent_running = False
    app._agent_worker = None
    app._mount_message = AsyncMock()
    app._try_recover_goal_completion_from_ledger = AsyncMock()
    app._cleanup_agent_task = AsyncMock()
    return app


@pytest.mark.asyncio
async def test_connection_drop_retries_turn_with_content(monkeypatch: Any) -> None:  # noqa: ANN401
    app = _execution_app()
    calls: list[bool] = []

    async def fake_execute(**kwargs: Any) -> SessionStats:
        calls.append(bool(kwargs["skip_daemon_send_turn"]))
        if len(calls) == 1:
            raise ConnectionError("Daemon connection lost")
        return SessionStats()

    monkeypatch.setattr("soothe_cli.tui.textual_adapter.execute_task_textual", fake_execute)

    await app._run_agent_task("/skill:omr-bootstrap go", skip_daemon_send_turn=True)

    assert calls == [True, False]
    app._mount_message.assert_not_awaited()


@pytest.mark.asyncio
async def test_connection_drop_without_content_is_not_retried(monkeypatch: Any) -> None:  # noqa: ANN401
    app = _execution_app()
    calls: list[bool] = []

    async def fake_execute(**kwargs: Any) -> SessionStats:
        calls.append(bool(kwargs["skip_daemon_send_turn"]))
        raise ConnectionError("Daemon connection lost")

    monkeypatch.setattr("soothe_cli.tui.textual_adapter.execute_task_textual", fake_execute)

    await app._run_agent_task("", skip_daemon_send_turn=True)

    assert calls == [True]
    mounted = app._mount_message.await_args_list[0].args[0]
    assert "Daemon connection error" in mounted._content
