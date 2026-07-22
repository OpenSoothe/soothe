"""Soothe workspace: loop resolution + explicit nano workspace re-exports."""

from soothe_nano.workspace.workspace_api import (
    ResolvedWorkspace,
    resolve_workspace_for_stream,
    resolve_workspace_for_tool_execution,
)
from soothe_nano.workspace.workspace_filesystem import (
    FrameworkFilesystem,
    NormalizedPathBackend,
    WorkspaceAwareBackend,
    get_workspace_backend,
)
from soothe_nano.workspace.workspace_runtime import (
    WorkspaceContext,
    clear_virtual_mode_context,
    get_virtual_home,
    get_virtual_home_relative_path,
    get_virtual_mode,
    set_virtual_mode_context,
)

from soothe.workspace.core_resolution import (
    WorkspacePrecedence,
    resolve_workspace,
)
from soothe.workspace.loop_workspace import (
    compute_scoped_workspace_dir_name,
    normalize_user_id,
    resolve_loop_workspace,
    resolve_persisted_loop_workspace,
)
from soothe.workspace.resolution import (
    cleanup_anonymous_workspaces,
    resolve_daemon_workspace,
    translate_client_path_to_container,
    translate_container_path_to_client,
    validate_client_workspace,
)
from soothe.workspace.scoped import user_id_for_hash

__all__ = [
    "FrameworkFilesystem",
    "NormalizedPathBackend",
    "ResolvedWorkspace",
    "WorkspaceAwareBackend",
    "WorkspaceContext",
    "WorkspacePrecedence",
    "cleanup_anonymous_workspaces",
    "clear_virtual_mode_context",
    "compute_scoped_workspace_dir_name",
    "get_virtual_home",
    "get_virtual_home_relative_path",
    "get_virtual_mode",
    "get_workspace_backend",
    "normalize_user_id",
    "resolve_daemon_workspace",
    "resolve_loop_workspace",
    "resolve_persisted_loop_workspace",
    "translate_client_path_to_container",
    "translate_container_path_to_client",
    "resolve_workspace_for_stream",
    "resolve_workspace_for_tool_execution",
    "set_virtual_mode_context",
    "user_id_for_hash",
    "validate_client_workspace",
    "resolve_workspace",
]
