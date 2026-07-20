"""Workspace management package."""

from soothe_nano.workspace.workspace_api import (
    ResolvedWorkspace,
    WorkspacePrecedence,
    resolve_workspace,
    resolve_workspace_for_stream,
    resolve_workspace_for_tool_execution,
)
from soothe_nano.workspace.workspace_filesystem import (
    FrameworkFilesystem,
    NormalizedPathBackend,
    WorkspaceAwareBackend,
    get_workspace_backend,
)
from soothe_nano.workspace.workspace_policy import (
    compute_scoped_workspace_dir_name,
    normalize_user_id,
    translate_client_path_to_container,
    translate_container_path_to_client,
    user_id_for_hash,
    validate_client_workspace,
)
from soothe_nano.workspace.workspace_runtime import (
    WorkspaceContext,
    clear_virtual_mode_context,
    get_virtual_home,
    get_virtual_home_relative_path,
    get_virtual_mode,
    set_virtual_mode_context,
)

__all__ = [
    "FrameworkFilesystem",
    "NormalizedPathBackend",
    "ResolvedWorkspace",
    "WorkspaceAwareBackend",
    "WorkspaceContext",
    "WorkspacePrecedence",
    "clear_virtual_mode_context",
    "compute_scoped_workspace_dir_name",
    "get_virtual_home",
    "get_virtual_home_relative_path",
    "get_virtual_mode",
    "get_workspace_backend",
    "normalize_user_id",
    "resolve_workspace",
    "resolve_workspace_for_stream",
    "resolve_workspace_for_tool_execution",
    "set_virtual_mode_context",
    "translate_client_path_to_container",
    "translate_container_path_to_client",
    "user_id_for_hash",
    "validate_client_workspace",
]
