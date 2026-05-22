"""Tests for client workspace propagation through ``loop_new`` (IG-409).

The CLI passes the user's CWD on bootstrap so the agent's filesystem tools default
to the user's project directory. ``_handle_loop_new`` must validate the value and
persist it in the database; ``bind_execution_thread_for_loop`` must prefer it
over the per-loop daemon scratch dir created by ``resolve_loop_daemon_workspace``.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
import soothe.config as soothe_config
from soothe.core.loop.state.persistence.manager import (
    AgentLoopCheckpointPersistenceManager,
)

from soothe_daemon.loop_isolation import bind_execution_thread_for_loop
from soothe_daemon.protocol import MessageRouter


async def _read_metadata(loop_id: str, config: Any) -> dict[str, Any]:
    """Read loop metadata from the database (replaces old metadata.json read)."""
    pm = AgentLoopCheckpointPersistenceManager(config=config)
    try:
        return await pm.get_loop_metadata(loop_id) or {}
    finally:
        await pm.close()


class _CapturingDaemon:
    """Minimal daemon double recording the response sent for ``loop_new``."""

    def __init__(self, config: Any = None) -> None:
        self.sent: list[dict[str, Any]] = []
        self._config = config
        self._persistence_manager: AgentLoopCheckpointPersistenceManager | None = None

    def _get_pm(self) -> AgentLoopCheckpointPersistenceManager:
        if self._persistence_manager is None:
            self._persistence_manager = AgentLoopCheckpointPersistenceManager(config=self._config)
        return self._persistence_manager

    @property
    def _pm(self) -> AgentLoopCheckpointPersistenceManager:
        return self._get_pm()

    async def _send_client_message(self, client_id: Any, msg: dict[str, Any]) -> None:
        self.sent.append(msg)

    async def close(self) -> None:
        if self._persistence_manager is not None:
            await self._persistence_manager.close()


def _make_daemon_with_pm(config: Any) -> _CapturingDaemon:
    daemon = _CapturingDaemon(config=config)
    # Pre-init the persistence manager so _handle_loop_new can use daemon._persistence_manager
    daemon._persistence_manager = AgentLoopCheckpointPersistenceManager(config=config)
    return daemon


@pytest.mark.asyncio
async def test_loop_new_persists_client_workspace(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A valid client workspace on ``loop_new`` is written into the database."""
    monkeypatch.setattr(soothe_config, "SOOTHE_HOME", str(tmp_path / "soothe-home"))

    project = tmp_path / "myproject"
    project.mkdir()

    from soothe.config import SootheConfig

    config = SootheConfig()
    daemon = _make_daemon_with_pm(config)
    router = MessageRouter(daemon)

    try:
        await router._handle_loop_new(
            client_id="client-1",
            msg={"type": "loop_new", "workspace": str(project), "request_id": "rid-1"},
        )

        assert daemon.sent, "Daemon must respond to loop_new"
        response = daemon.sent[-1]
        assert response["type"] == "loop_new_response"
        loop_id = response["loop_id"]
        assert loop_id

        metadata = await _read_metadata(loop_id, config)
        assert metadata.get("client_workspace") == str(project.resolve())
    finally:
        await daemon.close()


@pytest.mark.asyncio
async def test_loop_new_omits_client_workspace_when_invalid(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Unsafe workspace values (system dirs) are rejected without aborting loop creation."""
    monkeypatch.setattr(soothe_config, "SOOTHE_HOME", str(tmp_path / "soothe-home"))

    from soothe.config import SootheConfig

    config = SootheConfig()
    daemon = _make_daemon_with_pm(config)
    router = MessageRouter(daemon)

    try:
        await router._handle_loop_new(
            client_id="client-1",
            msg={"type": "loop_new", "workspace": "/", "request_id": "rid-2"},
        )

        response = daemon.sent[-1]
        loop_id = response["loop_id"]
        metadata = await _read_metadata(loop_id, config)
        assert metadata.get("client_workspace") is None
    finally:
        await daemon.close()


@pytest.mark.asyncio
async def test_loop_new_omits_client_workspace_when_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Without a ``workspace`` field the loop falls back to per-loop daemon dir."""
    monkeypatch.setattr(soothe_config, "SOOTHE_HOME", str(tmp_path / "soothe-home"))

    from soothe.config import SootheConfig

    config = SootheConfig()
    daemon = _make_daemon_with_pm(config)
    router = MessageRouter(daemon)

    try:
        await router._handle_loop_new(
            client_id="client-1",
            msg={"type": "loop_new", "request_id": "rid-3"},
        )

        response = daemon.sent[-1]
        loop_id = response["loop_id"]
        metadata = await _read_metadata(loop_id, config)
        assert metadata.get("client_workspace") is None
    finally:
        await daemon.close()


@pytest.mark.asyncio
async def test_bind_execution_thread_prefers_client_workspace(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``bind_execution_thread_for_loop`` registers the client_workspace, not the per-loop dir."""
    monkeypatch.setattr(soothe_config, "SOOTHE_HOME", str(tmp_path / "soothe-home"))

    project = tmp_path / "myproject"
    project.mkdir()

    from soothe.config import SootheConfig

    config = SootheConfig()
    daemon = _make_daemon_with_pm(config)
    router = MessageRouter(daemon)

    try:
        # Create loop via the same handler so metadata layout matches production.
        await router._handle_loop_new(
            client_id="client-1",
            msg={"type": "loop_new", "workspace": str(project), "request_id": "rid-1"},
        )
        loop_id = daemon.sent[-1]["loop_id"]

        # Stub the runtime daemon surfaces touched during bind.
        set_workspace_calls: list[Path] = []

        class _ThreadRegistry:
            def ensure(self, _thread_id: str, *, is_draft: bool) -> None:
                _ = is_draft

            def set_workspace(self, _thread_id: str, workspace: Path) -> None:
                set_workspace_calls.append(Path(workspace))

            def set_thread_loop(self, _thread_id: str, _loop_id: str) -> None:
                pass

        class _Runner:
            def set_current_thread_id(self, _thread_id: str) -> None:
                pass

        bind_daemon = SimpleNamespace(
            _persistence_manager=daemon._persistence_manager,
            _thread_registry=_ThreadRegistry(),
            _runner=_Runner(),
            _daemon_workspace=str(tmp_path / "fallback"),
        )

        checkpoint_thread_id = await bind_execution_thread_for_loop(bind_daemon, loop_id)

        assert checkpoint_thread_id != loop_id
        assert set_workspace_calls, "set_workspace must be invoked"
        assert set_workspace_calls[0] == project.resolve()
    finally:
        await daemon.close()


@pytest.mark.asyncio
async def test_bind_execution_thread_generates_distinct_thread_id(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """First bind mints a LangGraph thread id separate from the client loop_id."""
    monkeypatch.setattr(soothe_config, "SOOTHE_HOME", str(tmp_path / "soothe-home"))

    from soothe.config import SootheConfig

    config = SootheConfig()
    daemon = _make_daemon_with_pm(config)
    router = MessageRouter(daemon)

    try:
        await router._handle_loop_new(
            client_id="client-1",
            msg={"type": "loop_new", "request_id": "rid-1"},
        )
        loop_id = daemon.sent[-1]["loop_id"]

        class _ThreadRegistry:
            def ensure(self, _thread_id: str, *, is_draft: bool) -> None:
                _ = is_draft

            def set_workspace(self, _thread_id: str, _workspace: Path) -> None:
                pass

            def set_thread_loop(self, thread_id: str, bound_loop_id: str) -> None:
                assert bound_loop_id == loop_id
                assert thread_id != loop_id

        bind_daemon = SimpleNamespace(
            _persistence_manager=daemon._persistence_manager,
            _thread_registry=_ThreadRegistry(),
            _daemon_workspace=str(tmp_path / "fallback"),
        )

        checkpoint_thread_id = await bind_execution_thread_for_loop(bind_daemon, loop_id)
        assert checkpoint_thread_id != loop_id

        metadata = await daemon._persistence_manager.get_loop_metadata(loop_id)
        assert metadata is not None
        assert metadata.get("current_thread_id") == checkpoint_thread_id
        assert checkpoint_thread_id in (metadata.get("thread_ids") or [])
        assert loop_id not in (metadata.get("thread_ids") or [])
    finally:
        await daemon.close()


@pytest.mark.asyncio
async def test_bind_execution_thread_replaces_legacy_loop_id_alias(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Loops that incorrectly stored thread_id=loop_id get a fresh thread on re-bind."""
    monkeypatch.setattr(soothe_config, "SOOTHE_HOME", str(tmp_path / "soothe-home"))

    from soothe.config import SootheConfig

    config = SootheConfig()
    daemon = _make_daemon_with_pm(config)
    router = MessageRouter(daemon)

    try:
        await router._handle_loop_new(
            client_id="client-1",
            msg={"type": "loop_new", "request_id": "rid-1"},
        )
        loop_id = daemon.sent[-1]["loop_id"]
        await daemon._persistence_manager.update_loop_metadata(
            loop_id,
            current_thread_id=loop_id,
            thread_ids=[loop_id],
            status="running",
        )

        bind_daemon = SimpleNamespace(
            _persistence_manager=daemon._persistence_manager,
            _thread_registry=SimpleNamespace(
                ensure=lambda *_a, **_k: None,
                set_workspace=lambda *_a, **_k: None,
                set_thread_loop=lambda *_a, **_k: None,
            ),
            _daemon_workspace=str(tmp_path / "fallback"),
        )

        checkpoint_thread_id = await bind_execution_thread_for_loop(bind_daemon, loop_id)
        assert checkpoint_thread_id != loop_id

        metadata = await daemon._persistence_manager.get_loop_metadata(loop_id)
        assert metadata is not None
        assert metadata.get("current_thread_id") == checkpoint_thread_id
        assert loop_id not in (metadata.get("thread_ids") or [])
    finally:
        await daemon.close()


@pytest.mark.asyncio
async def test_bind_execution_thread_falls_back_when_client_workspace_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When metadata has no client_workspace use anonymous/ws_<hash(loop_id)>."""
    soothe_home = tmp_path / "soothe-home"
    monkeypatch.setattr(soothe_config, "SOOTHE_HOME", str(soothe_home))

    from soothe.config import SootheConfig
    from soothe.core.workspace.loop_workspace import (
        compute_scoped_workspace_dir_name,
        normalize_user_id,
    )

    config = SootheConfig()
    daemon = _make_daemon_with_pm(config)
    router = MessageRouter(daemon)

    try:
        await router._handle_loop_new(
            client_id="client-1",
            msg={"type": "loop_new", "request_id": "rid-1"},
        )
        loop_id = daemon.sent[-1]["loop_id"]

        set_workspace_calls: list[Path] = []

        class _ThreadRegistry:
            def ensure(self, _thread_id: str, *, is_draft: bool) -> None:
                _ = is_draft

            def set_workspace(self, _thread_id: str, workspace: Path) -> None:
                set_workspace_calls.append(Path(workspace))

            def set_thread_loop(self, _thread_id: str, _loop_id: str) -> None:
                pass

        class _Runner:
            def set_current_thread_id(self, _thread_id: str) -> None:
                pass

        bind_daemon = SimpleNamespace(
            _persistence_manager=daemon._persistence_manager,
            _thread_registry=_ThreadRegistry(),
            _runner=_Runner(),
            _daemon_workspace=str(tmp_path / "fallback"),
        )

        await bind_execution_thread_for_loop(bind_daemon, loop_id)

        assert set_workspace_calls, "set_workspace must be invoked"
        ws_name = compute_scoped_workspace_dir_name(None, loop_id)
        expected_loop_ws = soothe_home.resolve() / "workspaces" / normalize_user_id(None) / ws_name
        assert set_workspace_calls[0] == expected_loop_ws
    finally:
        await daemon.close()


@pytest.mark.asyncio
async def test_checkpoint_thread_id_overrides_stale_runner_for_workspace_resolution() -> None:
    """``bind`` sets registry workspace on the loop checkpoint; ``run_query`` must use that id.

    RFC-221 stopped mutating ``runner.current_thread_id`` inside ``bind_execution_thread_for_loop``.
    Without passing the bound checkpoint into ``run_query``, workspace resolution could read
    a stale singleton id and pass the wrong directory into ``LoopRunRequest``.
    """
    from soothe_daemon.query import QueryEngine

    class _Runner:
        def __init__(self) -> None:
            self.current_thread_id = "stale-global-thread"

        def set_current_thread_id(self, thread_id: str | None) -> None:
            self.current_thread_id = thread_id

    qe = QueryEngine.__new__(QueryEngine)
    qe._daemon = SimpleNamespace(_runner=_Runner())

    resolved = await QueryEngine._resolve_query_checkpoint_thread_id(
        qe,
        checkpoint_thread_id="bound-loop-thread",
        client_id=None,
    )
    assert resolved == "bound-loop-thread"
    assert qe._daemon._runner.current_thread_id == "bound-loop-thread"
