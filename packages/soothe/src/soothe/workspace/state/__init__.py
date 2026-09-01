"""Workspace state database — runtime cache for files, blobs, checkpoints, artifacts.

Follows the unified persistence backend pattern: SQLite in SQLite mode,
PostgreSQL tables in PostgreSQL mode.  The protocol is async to match
the rest of the workspace sync subsystem.
"""

from soothe.workspace.state.factory import create_workspace_state_store
from soothe.workspace.state.protocol import WorkspaceStateStore
from soothe.workspace.state.sqlite import SqliteWorkspaceStateStore

__all__ = [
    "SqliteWorkspaceStateStore",
    "WorkspaceStateStore",
    "create_workspace_state_store",
]
