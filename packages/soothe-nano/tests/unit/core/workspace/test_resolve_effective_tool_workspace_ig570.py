"""Tests for IG-570 unified tool workspace resolution."""

from __future__ import annotations

from contextvars import Token
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from soothe_nano.middleware.filesystem import SootheFilesystemMiddleware
from soothe_nano.workspace.workspace_filesystem import FrameworkFilesystem
from soothe_nano.workspace.workspace_paths import (
    resolve_effective_tool_workspace,
    workspace_path_for_tool_resolution,
)


@pytest.fixture
def workspace_token() -> Token[Path | None]:
    """Set and restore ContextVar workspace."""
    token = FrameworkFilesystem.set_current_workspace("/ctx/stream-workspace")
    yield token
    FrameworkFilesystem.clear_current_workspace(token)


def test_resolve_effective_tool_workspace_prefers_contextvar(
    workspace_token: Token[Path | None],
) -> None:
    """ContextVar stream workspace wins over daemon fallback."""
    resolved = resolve_effective_tool_workspace(None)
    assert resolved == Path("/ctx/stream-workspace").resolve()


def test_resolve_effective_tool_workspace_prefers_runtime_config() -> None:
    """ToolRuntime configurable workspace wins over static fallback."""
    runtime = MagicMock()
    runtime.config = {"configurable": {"workspace": "/client/from_runtime"}}
    runtime.state = {}

    resolved = resolve_effective_tool_workspace(None, runtime=runtime)
    assert resolved == Path("/client/from_runtime")


def test_workspace_path_for_tool_resolution_matches_effective(tmp_path: Path) -> None:
    """Tabular/media path helper uses the same resolver."""
    ws = tmp_path / "repo"
    ws.mkdir()
    token = FrameworkFilesystem.set_current_workspace(ws)
    try:
        assert workspace_path_for_tool_resolution(None) == ws.resolve()
    finally:
        FrameworkFilesystem.clear_current_workspace(token)


def test_soothe_filesystem_middleware_uses_runtime_workspace(tmp_path: Path) -> None:
    """Surgical file tools resolve backend from ToolRuntime workspace."""
    initial = tmp_path / "initial"
    initial.mkdir()
    stream = tmp_path / "stream"
    stream.mkdir()

    backend = MagicMock()
    backend.virtual_mode = False
    factory_calls: list[str] = []

    def factory(ws: str) -> MagicMock:
        factory_calls.append(ws)
        created = MagicMock()
        created.resolve_os_path = MagicMock(return_value=stream / "file.txt")
        return created

    middleware = SootheFilesystemMiddleware(
        backend=backend,
        workspace_root=str(initial),
        workspace_backend_factory=factory,
    )

    runtime = MagicMock()
    runtime.config = {"configurable": {"workspace": str(stream)}}
    runtime.state = {"workspace": str(stream)}

    resolved = middleware._get_backend(runtime)
    assert factory_calls == [str(stream)]
    assert resolved is not None
