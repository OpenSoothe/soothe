"""Tests for TUI daemon bootstrap and resume behavior."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from soothe.config import SootheConfig
from soothe.ux.cli.commands.thread_cmd import thread_continue
from soothe.ux.tui import app as tui_app


def test_start_daemon_uses_external_process(monkeypatch, tmp_path: Path) -> None:
    spawned: list[list[str]] = []
    ready_socket = tmp_path / "soothe.sock"
    ready_socket.write_text("")

    monkeypatch.setattr(tui_app.SootheDaemon, "is_running", staticmethod(lambda: False))
    monkeypatch.setattr(tui_app, "socket_path", lambda: ready_socket)
    monkeypatch.setattr(tui_app.subprocess, "Popen", lambda cmd, **_kwargs: spawned.append(cmd))

    tui_app._start_daemon_in_background(SootheConfig(), config_path="/tmp/custom.yml")

    assert spawned
    assert spawned[0][:3] == [spawned[0][0], "-m", "soothe.daemon"]
    assert "--config" in spawned[0]
    assert "/tmp/custom.yml" in spawned[0]


def test_start_daemon_skips_when_already_running(monkeypatch) -> None:
    spawned = {"count": 0}
    monkeypatch.setattr(tui_app.SootheDaemon, "is_running", staticmethod(lambda: True))
    monkeypatch.setattr(tui_app.subprocess, "Popen", lambda *args, **kwargs: spawned.__setitem__("count", 1))

    tui_app._start_daemon_in_background(SootheConfig())

    assert spawned["count"] == 0


class _FakeConversationPanel:
    def __init__(self) -> None:
        self.entries: list[Any] = []
        self.cleared = 0

    def append_entry(self, renderable: Any) -> None:
        self.entries.append(renderable)

    def update_last_entry(self, renderable: Any) -> None:
        if self.entries:
            self.entries[-1] = renderable
        else:
            self.entries.append(renderable)

    def clear(self) -> None:
        self.cleared += 1
        self.entries.clear()


class _FakeChatInput:
    def __init__(self) -> None:
        self.history: list[str] = []

    def set_history(self, history: list[str]) -> None:
        self.history = history

    def focus(self) -> None:
        return None


class _FakeInfoBar:
    def __init__(self) -> None:
        self.value = ""

    def update(self, text: str) -> None:
        self.value = text


class _FakePlanTree:
    def __init__(self) -> None:
        self.content = ""
        self.visible = False

    def update(self, content: str) -> None:
        self.content = content

    def add_class(self, _name: str) -> None:
        self.visible = True

    def remove_class(self, _name: str) -> None:
        self.visible = False


class _FakeDaemonClient:
    def __init__(self, events: list[dict[str, Any] | None]) -> None:
        self._events = list(events)
        self.resume_thread_calls: list[str] = []
        self.new_thread_calls = 0
        self.subscribe_calls: list[str] = []

    async def connect(self) -> None:
        return None

    async def send_resume_thread(self, thread_id: str) -> None:
        self.resume_thread_calls.append(thread_id)

    async def send_new_thread(self) -> None:
        self.new_thread_calls += 1

    async def read_event(self) -> dict[str, Any] | None:
        if not self._events:
            return None
        return self._events.pop(0)

    async def subscribe_thread(self, thread_id: str) -> None:
        self.subscribe_calls.append(thread_id)

    async def wait_for_subscription_confirmed(self, thread_id: str) -> None:
        return None


def _mount_fake_widgets(app: tui_app.SootheApp) -> dict[str, Any]:
    conversation = _FakeConversationPanel()
    chat_input = _FakeChatInput()
    info_bar = _FakeInfoBar()
    plan_tree = _FakePlanTree()
    widgets = {
        "#conversation": conversation,
        "#chat-input": chat_input,
        "#info-bar": info_bar,
        "#plan-tree": plan_tree,
    }
    app.query_one = lambda selector, *_args: widgets[selector]  # type: ignore[method-assign]
    return widgets


@pytest.mark.asyncio
async def test_connect_and_listen_restores_history_from_initial_resume_status(monkeypatch) -> None:
    """Startup resume should render conversation history from the first status event."""
    status_event = {
        "type": "status",
        "state": "idle",
        "thread_id": "thread-123",
        "thread_resumed": True,
        "input_history": ["hello again"],
        "conversation_history": [
            {"role": "user", "text": "hello"},
            {"role": "assistant", "text": "hi there"},
        ],
    }
    client = _FakeDaemonClient(events=[status_event, None])
    monkeypatch.setattr(tui_app, "DaemonClient", lambda: client)

    app = tui_app.SootheApp(config=SootheConfig(), thread_id="thread-123")
    widgets = _mount_fake_widgets(app)

    await app._connect_and_listen()

    assert client.resume_thread_calls == ["thread-123"]
    assert client.new_thread_calls == 0
    assert client.subscribe_calls == ["thread-123"]
    assert widgets["#chat-input"].history == ["hello again"]
    assert widgets["#conversation"].cleared == 1
    rendered_entries = [str(entry) for entry in widgets["#conversation"].entries]
    assert any("Resuming conversation" in entry for entry in rendered_entries)
    assert any("hello" in entry for entry in rendered_entries)
    assert any("hi there" in entry for entry in rendered_entries)


@pytest.mark.asyncio
async def test_connect_and_listen_does_not_create_new_thread_on_missing_resume(monkeypatch) -> None:
    """Explicit resume failure should surface an error instead of creating a new thread."""
    client = _FakeDaemonClient(
        events=[
            {"type": "error", "code": "THREAD_NOT_FOUND", "message": "Thread missing"},
        ]
    )
    monkeypatch.setattr(tui_app, "DaemonClient", lambda: client)

    app = tui_app.SootheApp(config=SootheConfig(), thread_id="missing-thread")
    widgets = _mount_fake_widgets(app)

    await app._connect_and_listen()

    assert client.resume_thread_calls == ["missing-thread"]
    assert client.new_thread_calls == 0
    rendered_entries = [str(entry) for entry in widgets["#conversation"].entries]
    assert any("Thread missing" in entry for entry in rendered_entries)


def test_thread_continue_uses_daemon_thread_listing_when_daemon_running(monkeypatch) -> None:
    """Omitted thread IDs should resolve through the daemon when one is already running."""
    captured: dict[str, Any] = {}

    class _FakeThreadClient:
        async def connect(self) -> None:
            return None

        async def send_thread_list(self) -> None:
            return None

        async def read_event(self) -> dict[str, Any]:
            return {
                "type": "thread_list_response",
                "threads": [
                    {"thread_id": "older", "status": "idle", "updated_at": "2026-03-25T00:00:00+00:00"},
                    {"thread_id": "latest", "status": "active", "updated_at": "2026-03-25T00:01:00+00:00"},
                ],
            }

        async def close(self) -> None:
            return None

    monkeypatch.setattr("soothe.ux.core.load_config", lambda _config: SootheConfig())
    monkeypatch.setattr("soothe.ux.core.setup_logging", lambda _cfg: None)
    monkeypatch.setattr(
        "soothe.ux.cli.execution.run_tui",
        lambda cfg, thread_id=None, config_path=None: captured.update(
            {"thread_id": thread_id, "config_path": config_path}
        ),
    )
    monkeypatch.setattr("soothe.daemon.DaemonClient", _FakeThreadClient)
    monkeypatch.setattr("soothe.daemon.SootheDaemon.is_running", staticmethod(lambda: True))

    thread_continue(thread_id=None, config="config.yml", daemon=False, new=False)

    assert captured["thread_id"] == "latest"
    assert captured["config_path"] == "config.yml"
