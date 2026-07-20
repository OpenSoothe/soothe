"""Shared catalog and builders for filesystem tools.

This module centralizes canonical surgical file-operation tool naming and
construction so resolver and plugin paths stay aligned.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence

from langchain_core.tools import BaseTool
from soothe_deepagents.backends.protocol import BackendProtocol

from soothe_nano.middleware.filesystem import SootheFilesystemMiddleware

SURGICAL_FILE_OP_TOOL_NAMES: tuple[str, ...] = (
    "delete",
    "file_info",
    "edit_lines",
    "insert_lines",
    "delete_lines",
    "apply_diff",
)
"""Canonical surgical file-operation tool names exposed by `file_ops`."""

SURGICAL_FILE_OP_TOOL_NAME_SET: frozenset[str] = frozenset(SURGICAL_FILE_OP_TOOL_NAMES)


def build_filesystem_tools(
    *,
    backend: BackendProtocol,
    tool_names: Sequence[str] | None = None,
    backup_enabled: bool = True,
    backup_dir: str | None = None,
    workspace_root: str | None = None,
    workspace_backend_factory: Callable[[str], BackendProtocol] | None = None,
    tool_token_limit_before_evict: int = 20000,
) -> list[BaseTool]:
    """Build filesystem tools via `SootheFilesystemMiddleware`.

    Args:
        backend: Filesystem backend for tool operations.
        tool_names: Optional explicit subset of filesystem tool names to expose.
        backup_enabled: Compatibility flag passed to middleware.
        backup_dir: Optional backup directory for delete operations.
        workspace_root: Effective workspace root.
        workspace_backend_factory: Optional per-workspace backend factory.
        tool_token_limit_before_evict: Eviction threshold in characters.

    Returns:
        Instantiated filesystem tools in middleware-defined order.
    """
    middleware_kwargs: dict[str, object] = {
        "backend": backend,
        "backup_enabled": backup_enabled,
        "backup_dir": backup_dir,
        "workspace_root": workspace_root,
        "workspace_backend_factory": workspace_backend_factory,
        "tool_token_limit_before_evict": tool_token_limit_before_evict,
    }
    if tool_names is not None:
        middleware_kwargs["tools"] = list(tool_names)

    middleware = SootheFilesystemMiddleware(**middleware_kwargs)
    return list(middleware.tools)


def build_surgical_file_ops_tools(
    *,
    backend: BackendProtocol,
    backup_enabled: bool = True,
    backup_dir: str | None = None,
    workspace_root: str | None = None,
    workspace_backend_factory: Callable[[str], BackendProtocol] | None = None,
    tool_token_limit_before_evict: int = 20000,
) -> list[BaseTool]:
    """Build the canonical surgical `file_ops` tool set."""
    # deepagents FilesystemMiddleware requires `read_file` in any explicit
    # allowlist; include it for construction, then drop it from returned tools.
    tools = build_filesystem_tools(
        backend=backend,
        tool_names=("read_file", *SURGICAL_FILE_OP_TOOL_NAMES),
        backup_enabled=backup_enabled,
        backup_dir=backup_dir,
        workspace_root=workspace_root,
        workspace_backend_factory=workspace_backend_factory,
        tool_token_limit_before_evict=tool_token_limit_before_evict,
    )
    return [tool for tool in tools if getattr(tool, "name", None) in SURGICAL_FILE_OP_TOOL_NAME_SET]
