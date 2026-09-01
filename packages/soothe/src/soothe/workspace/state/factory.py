"""Factory for creating workspace state stores.

Follows the unified persistence backend pattern: `persistence.default_backend`
selects SQLite or PostgreSQL.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

from soothe.workspace.state.sqlite import SqliteWorkspaceStateStore

if TYPE_CHECKING:
    from soothe.workspace.state.protocol import WorkspaceStateStore

logger = logging.getLogger(__name__)


def create_workspace_state_store(
    config: Any,
    run_id: str,
    workspace_dir: Path | None = None,
) -> WorkspaceStateStore:
    """Create a workspace state store based on `persistence.default_backend`.

    Args:
        config: SootheConfig instance.
        run_id: Unique run identifier.
        workspace_dir: Workspace root directory (required for SQLite mode).

    Returns:
        A `WorkspaceStateStore` instance.

    Raises:
        ValueError: If the backend is unknown or SQLite mode lacks
            `workspace_dir`.
    """
    backend = config.persistence.default_backend

    if backend == "sqlite":
        if workspace_dir is None:
            raise ValueError("workspace_dir is required for SQLite workspace state store")
        db_path = workspace_dir / ".workspace" / "state.db"
        return SqliteWorkspaceStateStore(db_path=db_path, run_id=run_id)

    if backend == "postgresql":
        raise NotImplementedError(
            "PostgresWorkspaceStateStore is not yet implemented; "
            "use SQLite mode for workspace sync development"
        )

    raise ValueError(f"Unknown persistence backend: {backend!r}")
