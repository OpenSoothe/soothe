"""Tests for IG-316 tool path resolution helpers."""

from __future__ import annotations

from pathlib import Path

from langchain.tools import ToolRuntime

from soothe_nano.workspace.workspace_paths import (
    filesystem_virtual_mode_from_soothe_config,
    join_workspace_normalized_path,
    resolve_backend_os_path,
    should_use_virtual_path_resolution,
)


def _tool_runtime(tool_call_id: str = "tc") -> ToolRuntime:
    return ToolRuntime(
        state={"messages": [], "files": {}},
        context=None,
        tool_call_id=tool_call_id,
        store=None,
        stream_writer=lambda _: None,
        config={},
    )


def test_resolve_backend_os_path_virtual_mode_maps_absolute(tmp_path: Path) -> None:
    """Virtual paths like ``/a.txt`` map under workspace root."""
    ws = tmp_path / "ws"
    ws.mkdir()
    resolved = resolve_backend_os_path("/nested/file.txt", workspace=ws, virtual_mode=True)
    assert resolved == ws / "nested" / "file.txt"


def test_resolve_backend_os_path_virtual_mode_host_absolute_under_workspace(
    tmp_path: Path,
) -> None:
    """Host-absolute paths inside the workspace resolve under the root (virtual mode)."""
    ws = tmp_path / "repo"
    ws.mkdir()
    target = ws / "README.md"
    target.write_text("hello", encoding="utf-8")

    resolved = resolve_backend_os_path(str(target.resolve()), workspace=ws, virtual_mode=True)
    assert resolved.resolve() == target.resolve()


def test_should_use_virtual_path_resolution(tmp_path: Path) -> None:
    """Virtual absolutes use sandbox resolution; host roots do not."""
    ws = tmp_path / "repo"
    ws.mkdir()
    assert should_use_virtual_path_resolution("/README.md", ws) is True
    assert should_use_virtual_path_resolution("/", ws) is True
    assert should_use_virtual_path_resolution("/tmp/outside", ws) is False
    assert should_use_virtual_path_resolution("README.md", ws) is False


def test_join_workspace_normalized_path_handles_absolute(tmp_path: Path) -> None:
    """Absolute normalized paths must not be joined with workspace prefix."""
    ws = tmp_path / "repo"
    ws.mkdir()
    host = ws / "README.md"
    host.write_text("hi", encoding="utf-8")
    resolved = join_workspace_normalized_path(ws, str(host.resolve()))
    assert resolved.resolve() == host.resolve()


def test_normalized_path_backend_read_host_absolute_under_workspace(tmp_path: Path) -> None:
    """Host-absolute paths inside the workspace resolve with ``virtual_mode=True`` (IG-300)."""
    from soothe_nano.workspace.workspace_filesystem import NormalizedPathBackend

    ws = tmp_path / "repo"
    ws.mkdir()
    target = ws / "packages" / "pkg" / "README.md"
    target.parent.mkdir(parents=True)
    target.write_text("hello", encoding="utf-8")

    backend = NormalizedPathBackend(
        root_dir=str(ws),
        virtual_mode=True,
        max_file_size_mb=10,
    )
    host_path = str(target)
    out = backend.read(host_path)
    assert out.error is None, out.error
    assert out.file_data is not None
    text = out.file_data["content"]
    assert "Error: File" not in text
    assert "hello" in text


def test_workspace_aware_backend_ls_info_host_absolute_under_workspace(tmp_path: Path) -> None:
    """``WorkspaceAwareBackend.ls_info`` accepts host-absolute dirs when ``virtual_mode=True`` (IG-300)."""
    from soothe_nano.workspace.workspace_filesystem import WorkspaceAwareBackend

    ws = tmp_path / "repo"
    ws.mkdir()
    (ws / "a.txt").write_text("x", encoding="utf-8")

    backend = WorkspaceAwareBackend(default_root_dir=ws, virtual_mode=True, max_file_size_mb=10)
    rows = backend.ls_info(str(ws))
    paths = [r.get("path", "") for r in rows]
    assert any("a.txt" in p for p in paths)


def test_filesystem_middleware_file_info_virtual_path(tmp_path: Path) -> None:
    """Surgical ``file_info`` resolves virtual absolute paths via backend (IG-316)."""
    from soothe_deepagents.backends.filesystem import FilesystemBackend

    from soothe_nano.middleware.filesystem import SootheFilesystemMiddleware

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
    out = tool.func(path="/note.txt", runtime=_tool_runtime())
    assert out is not None
    assert "File not found" not in out.content
    assert "note.txt" in out.content


def test_filesystem_virtual_mode_from_soothe_config() -> None:
    """``virtual_mode`` mirrors ``FrameworkFilesystem`` security flag."""
    from soothe_nano.config.settings import SootheConfig

    cfg = SootheConfig()
    cfg.security.allow_paths_outside_workspace = False
    assert filesystem_virtual_mode_from_soothe_config(cfg) is True
    cfg.security.allow_paths_outside_workspace = True
    assert filesystem_virtual_mode_from_soothe_config(cfg) is False


def test_resolve_file_ops_file_info_virtual_path_with_soothe_config(tmp_path: Path) -> None:
    """Resolver-built file_ops tools use ``virtual_mode`` from ``SootheConfig``."""
    from soothe.runner.resolver._resolver_tools import _resolve_single_tool_group_uncached

    from soothe_nano.config.settings import SootheConfig

    wdir = tmp_path / "agent_ws"
    wdir.mkdir()
    (wdir / "marks.csv").write_text("a,b\n1,2\n")

    cfg = SootheConfig()
    cfg.filesystem_middleware.workspace_root = str(wdir)
    cfg.security.allow_paths_outside_workspace = False

    tools = _resolve_single_tool_group_uncached("file_ops", config=cfg)
    file_info = next(t for t in tools if t.name == "file_info")
    out = file_info.func(path="/marks.csv", runtime=_tool_runtime())
    assert out is not None
    assert "File not found" not in out.content
    assert "marks.csv" in out.content or "bytes" in out.content.lower()


def test_get_data_info_resolves_virtual_path(tmp_path: Path) -> None:
    """Data toolkit resolves virtual paths when ``SootheConfig`` is set."""
    from soothe_nano.config.settings import SootheConfig
    from soothe_nano.toolkits.data import GetDataInfoTool

    wdir = tmp_path / "agent_ws"
    wdir.mkdir()
    (wdir / "data.csv").write_text("x\n")

    cfg = SootheConfig()
    cfg.filesystem_middleware.workspace_root = str(wdir)
    cfg.security.allow_paths_outside_workspace = False

    tool = GetDataInfoTool(config=cfg)
    out = tool.invoke({"file_path": "/data.csv"})
    assert "File not found" not in out
    assert "data.csv" in out or "Size" in out


def test_soothe_filesystem_middleware_uses_workspace_relative_artifact_prefix(
    tmp_path: Path,
) -> None:
    """SootheFilesystemMiddleware overrides soothe_deepagents' root-absolute artifact prefixes.

    Deepagents defaults `_large_tool_results_prefix` to "/large_tool_results" when
    the backend is not a CompositeBackend. On read-only root filesystems (macOS), this
    causes OSError. SootheFilesystemMiddleware must override to workspace-relative paths.
    """
    from soothe_deepagents.backends.filesystem import FilesystemBackend

    from soothe_nano.middleware.filesystem import SootheFilesystemMiddleware

    ws = tmp_path / "ws"
    ws.mkdir()

    backend = FilesystemBackend(root_dir=str(ws), virtual_mode=True, max_file_size_mb=10)
    mw = SootheFilesystemMiddleware(backend=backend, workspace_root=str(ws))

    # Verify prefixes are workspace-relative (no leading /)
    assert not mw._large_tool_results_prefix.startswith("/")
    assert not mw._conversation_history_prefix.startswith("/")
    assert mw._large_tool_results_prefix == ".soothe/large_tool_results"
    assert mw._conversation_history_prefix == ".soothe/conversation_history"


def test_normalized_backend_read_host_absolute_outside_workspace_rejected_on_write(
    tmp_path: Path,
) -> None:
    """Writes to host absolutes outside the workspace remain blocked in virtual mode."""
    from soothe_nano.workspace.workspace_filesystem import NormalizedPathBackend

    ws = tmp_path / "repo"
    ws.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("keep\n", encoding="utf-8")

    backend = NormalizedPathBackend(root_dir=ws, virtual_mode=True)
    result = backend.write(str(outside.resolve()), "changed\n")
    assert result.error is not None


def test_resolve_backend_os_path_host_absolute_outside_workspace(tmp_path: Path) -> None:
    """``resolve_backend_os_path`` follows host absolutes outside the workspace."""
    ws = tmp_path / "repo"
    ws.mkdir()
    outside = tmp_path / "runtime" / "soothe.log"
    outside.parent.mkdir()
    outside.write_text("x\n", encoding="utf-8")

    resolved = resolve_backend_os_path(
        str(outside.resolve()),
        workspace=ws,
        virtual_mode=True,
    )
    assert resolved.resolve() == outside.resolve()


def test_normalized_backend_multi_level_path_allowed_non_virtual_mode(tmp_path: Path) -> None:
    """Multi-level absolute paths are allowed in non-virtual mode.

    Paths like `/Users/xxx/file` are legitimate user file paths and should work
    when virtual_mode=False and allow_paths_outside_workspace=True.
    """
    from soothe_nano.workspace.workspace_filesystem import NormalizedPathBackend

    ws = tmp_path / "repo"
    ws.mkdir()

    # Create a file outside workspace in a valid location
    outside_dir = tmp_path / "outside"
    outside_dir.mkdir()
    outside_file = outside_dir / "data.txt"
    outside_file.write_text("external data")

    backend = NormalizedPathBackend(
        root_dir=str(ws),
        virtual_mode=False,
        max_file_size_mb=10,
    )

    # Multi-level absolute path should work in non-virtual mode
    result = backend.read(str(outside_file))
    assert result.error is None, result.error
    assert result.file_data is not None
    assert "external data" in result.file_data["content"]
