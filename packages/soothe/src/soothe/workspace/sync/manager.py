"""WorkspaceManager — lifecycle orchestrator for agent workspaces.

Creates, opens, recovers, and closes workspaces.  Wires together the CAS
cache, dirty tracker, debouncer, checkpoint manager, and background
uploader for each run.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

from soothe_sdk.protocols.workspace_sync import WorkspaceSyncBackend

from soothe.workspace.sync.cas import CASCache
from soothe.workspace.sync.checkpoint import CheckpointManager
from soothe.workspace.sync.debouncer import CheckpointDebouncer
from soothe.workspace.sync.dirty_tracker import DirtyTracker
from soothe.workspace.sync.uploader import BackgroundUploader
from soothe.workspace.sync.workspace import Workspace

if TYPE_CHECKING:
    from soothe.workspace.state.protocol import WorkspaceStateStore

logger = logging.getLogger(__name__)

_DEFAULT_CAS_ROOT = "data/agent-cache"


class WorkspaceManager:
    """Lifecycle orchestrator for agent workspaces.

    Creates workspace directories, wires together all sync components
    (CAS, dirty tracker, debouncer, checkpoint manager, uploader), and
    provides open/recover/close lifecycle operations.

    Args:
        workspaces_root: Root directory for workspace runs.
        cas_root: Root directory for the CAS cache.
        backend: Remote storage backend (or `None` for local-only mode).
        state_store_factory: Callable that creates a `WorkspaceStateStore`
            for a given run_id and workspace_dir.
    """

    def __init__(
        self,
        *,
        workspaces_root: Path,
        cas_root: Path,
        backend: WorkspaceSyncBackend | None = None,
        state_store_factory: type[WorkspaceStateStore] | None = None,
    ) -> None:
        self._workspaces_root = workspaces_root
        self._cas_root = cas_root
        self._backend = backend
        self._state_store_factory = state_store_factory
        self._workspaces: dict[str, Workspace] = {}

    def _workspace_root(self, run_id: str) -> Path:
        """Return the workspace root path for a run."""
        return self._workspaces_root / run_id

    def _create_workspace_dirs(self, run_id: str) -> Path:
        """Create the workspace directory structure.

        Args:
            run_id: Unique run identifier.

        Returns:
            Path to the created workspace root.
        """
        root = self._workspace_root(run_id)
        (root / "input").mkdir(parents=True, exist_ok=True)
        (root / "working").mkdir(parents=True, exist_ok=True)
        (root / "output").mkdir(parents=True, exist_ok=True)
        (root / ".workspace").mkdir(parents=True, exist_ok=True)
        return root

    async def open(self, run_id: str) -> Workspace:
        """Open a workspace for a run.

        Creates the workspace directory structure, initializes all sync
        components, and returns a `Workspace` handle.

        Args:
            run_id: Unique run identifier.

        Returns:
            A `Workspace` handle ready for materialization.
        """
        root = self._create_workspace_dirs(run_id)
        cas = CASCache(cache_root=self._cas_root)

        state_store: WorkspaceStateStore | None = None
        if self._state_store_factory is not None:
            state_store = self._state_store_factory(
                run_id=run_id,
                workspace_dir=root,
            )

        dirty_tracker = DirtyTracker(workspace_root=root)

        backend = self._backend
        if backend is None:
            logger.warning(
                "Opening workspace %s without a remote backend — "
                "checkpointing to remote is disabled",
                run_id,
            )

        checkpoint_mgr: CheckpointManager | None = None
        if backend is not None:
            checkpoint_mgr = CheckpointManager(
                run_id=run_id,
                backend=backend,
                cas=cas,
                dirty_tracker=dirty_tracker,
                workspace_root=root,
            )

        debouncer: CheckpointDebouncer | None = None
        if checkpoint_mgr is not None:
            debouncer = CheckpointDebouncer(
                trigger=checkpoint_mgr.create_checkpoint,
            )

        uploader: BackgroundUploader | None = None
        if backend is not None and state_store is not None:
            uploader = BackgroundUploader(
                backend=backend,
                store=state_store,
            )

        ws = Workspace(
            run_id=run_id,
            root=root,
            backend=backend,
            cas=cas,
            state_store=state_store,
            dirty_tracker=dirty_tracker,
            debouncer=debouncer,
            checkpoint_mgr=checkpoint_mgr,
            uploader=uploader,
        )
        self._workspaces[run_id] = ws
        logger.info("Opened workspace for run %s at %s", run_id, root)
        return ws

    async def open_from_uri(
        self,
        run_id: str,
        backend: WorkspaceSyncBackend,
    ) -> Workspace:
        """Open a workspace with a specific backend (e.g. from a URI).

        Args:
            run_id: Unique run identifier.
            backend: Remote storage backend to use for this run.

        Returns:
            A `Workspace` handle.
        """
        self._backend = backend
        return await self.open(run_id)

    def get(self, run_id: str) -> Workspace | None:
        """Get an already-open workspace by run ID.

        Args:
            run_id: Unique run identifier.

        Returns:
            The workspace handle, or `None` if not open.
        """
        return self._workspaces.get(run_id)

    async def close(self, run_id: str) -> None:
        """Close and remove a workspace from the active set.

        Args:
            run_id: Unique run identifier.
        """
        ws = self._workspaces.pop(run_id, None)
        if ws is not None:
            await ws.close()

    async def close_all(self) -> None:
        """Close all open workspaces."""
        run_ids = list(self._workspaces.keys())
        for run_id in run_ids:
            await self.close(run_id)
