"""Tests for IG-316 tool path resolution helpers."""

from __future__ import annotations

from pathlib import Path

from soothe.core.workspace.tool_path_resolution import (
    filesystem_virtual_mode_from_soothe_config,
    resolve_backend_os_path,
)


def test_resolve_backend_os_path_virtual_mode_maps_absolute(tmp_path: Path) -> None:
    """Virtual paths like ``/a.txt`` map under workspace root."""
    ws = tmp_path / "ws"
    ws.mkdir()
    resolved = resolve_backend_os_path("/nested/file.txt", workspace=ws, virtual_mode=True)
    assert resolved == ws / "nested" / "file.txt"


def test_filesystem_middleware_file_info_virtual_path(tmp_path: Path) -> None:
    """Surgical ``file_info`` resolves virtual absolute paths via backend (IG-316)."""
    from deepagents.backends.filesystem import FilesystemBackend

    from soothe.middleware.filesystem import SootheFilesystemMiddleware

    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "note.txt").write_text("hello")

    backend = FilesystemBackend(
        root_dir=str(ws),
        virtual_mode=True,
        max_file_size_mb=10,
    )
    mw = SootheFilesystemMiddleware(backend=backend, workspace_root=str(ws))
    tool = next(t for t in mw.tools if t.name == "file_info")
    out = tool.invoke({"path": "/note.txt"})
    assert "File not found" not in out
    assert "note.txt" in out


def test_filesystem_virtual_mode_from_soothe_config() -> None:
    """``virtual_mode`` mirrors ``FrameworkFilesystem`` security flag."""
    from soothe.config import SootheConfig

    cfg = SootheConfig()
    cfg.security.allow_paths_outside_workspace = False
    assert filesystem_virtual_mode_from_soothe_config(cfg) is True
    cfg.security.allow_paths_outside_workspace = True
    assert filesystem_virtual_mode_from_soothe_config(cfg) is False


def test_resolve_file_ops_file_info_virtual_path_with_soothe_config(tmp_path: Path) -> None:
    """Resolver-built file_ops tools use ``virtual_mode`` from ``SootheConfig``."""
    from soothe.config import SootheConfig
    from soothe.core.resolver._resolver_tools import _resolve_single_tool_group_uncached

    wdir = tmp_path / "agent_ws"
    wdir.mkdir()
    (wdir / "marks.csv").write_text("a,b\n1,2\n")

    cfg = SootheConfig()
    cfg.workspace_dir = str(wdir)
    cfg.security.allow_paths_outside_workspace = False

    tools = _resolve_single_tool_group_uncached("file_ops", config=cfg)
    file_info = next(t for t in tools if t.name == "file_info")
    out = file_info.invoke({"path": "/marks.csv"})
    assert "File not found" not in out
    assert "marks.csv" in out or "bytes" in out.lower()


def test_get_data_info_resolves_virtual_path(tmp_path: Path) -> None:
    """Data toolkit resolves virtual paths when ``SootheConfig`` is set."""
    from soothe.config import SootheConfig
    from soothe.toolkits.data import GetDataInfoTool

    wdir = tmp_path / "agent_ws"
    wdir.mkdir()
    (wdir / "data.csv").write_text("x\n")

    cfg = SootheConfig()
    cfg.workspace_dir = str(wdir)
    cfg.security.allow_paths_outside_workspace = False

    tool = GetDataInfoTool(config=cfg)
    out = tool.invoke({"file_path": "/data.csv"})
    assert "File not found" not in out
    assert "data.csv" in out or "Size" in out
