"""Workspace handle — per-run lifecycle: open, materialize, checkpoint, publish, close.

The `Workspace` is the agent-facing handle to a single run's workspace.
It coordinates the CAS cache, dirty tracker, debouncer, checkpoint
manager, and background uploader to provide a simple async lifecycle API.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

from soothe_sdk.protocols.workspace_sync import (
    Artifact,
    ArtifactSpec,
    Manifest,
    Resource,
)

from soothe.workspace.sync.cas import CASCache
from soothe.workspace.sync.checkpoint import CheckpointManager
from soothe.workspace.sync.debouncer import CheckpointDebouncer
from soothe.workspace.sync.dirty_tracker import DirtyTracker
from soothe.workspace.sync.materializer import Materializer
from soothe.workspace.sync.uploader import BackgroundUploader

if TYPE_CHECKING:
    from soothe_sdk.protocols.workspace_sync import WorkspaceSyncBackend

    from soothe.workspace.state.protocol import WorkspaceStateStore

logger = logging.getLogger(__name__)


class Workspace:
    """Per-run workspace handle.

    Coordinates materialization, dirty tracking, checkpointing, and
    publication for a single agent run.

    Args:
        run_id: Unique run identifier.
        root: Local filesystem root of the workspace.
        backend: Remote storage backend.
        cas: Local CAS cache.
        state_store: Workspace state database.
        dirty_tracker: Dirty file tracker.
        debouncer: Debounced checkpoint trigger.
        checkpoint_mgr: Checkpoint lifecycle manager.
        uploader: Background uploader.
    """

    def __init__(
        self,
        *,
        run_id: str,
        root: Path,
        backend: WorkspaceSyncBackend | None,
        cas: CASCache,
        state_store: WorkspaceStateStore | None,
        dirty_tracker: DirtyTracker,
        debouncer: CheckpointDebouncer | None,
        checkpoint_mgr: CheckpointManager | None,
        uploader: BackgroundUploader | None,
    ) -> None:
        self.run_id = run_id
        self.root = root
        self._backend = backend
        self._cas = cas
        self._state_store = state_store
        self._dirty_tracker = dirty_tracker
        self._debouncer = debouncer
        self._checkpoint_mgr = checkpoint_mgr
        self._uploader = uploader
        self._closing = False
        self._manifest: Manifest | None = None

    @property
    def closing(self) -> bool:
        """Return `True` if the workspace is in shutdown."""
        return self._closing

    @property
    def manifest(self) -> Manifest | None:
        """Return the current manifest, or `None` if not yet loaded."""
        return self._manifest

    async def materialize(self, resources: list[Resource]) -> None:
        """Materialize resources into the local workspace.

        Downloads missing blobs from the backend, stores them in CAS,
        and creates local file representations (reflink/hardlink/copy).

        Args:
            resources: List of resources to materialize.
        """
        materializer = Materializer(
            backend=self._backend,
            cas=self._cas,
            workspace_root=self.root,
        )
        await materializer.materialize(resources)
        logger.info("Materialized %d resources for run %s", len(resources), self.run_id)

    async def start_tracking(self) -> None:
        """Start dirty tracking and background uploader.

        Call after materialization, before the agent begins work.
        """
        self._dirty_tracker.start()
        self._uploader.start()
        self._debouncer.start()
        logger.info("Started tracking for run %s", self.run_id)

    async def checkpoint(self) -> str | None:
        """Create a checkpoint of the current dirty state.

        Returns:
            Checkpoint ID, or `None` if nothing was dirty.
        """
        if self._closing:
            logger.warning("Checkpoint skipped — workspace is closing")
            return None

        dirty = self._dirty_tracker.get_dirty()
        deleted = self._dirty_tracker.get_deleted()
        if not dirty and not deleted:
            logger.debug("No dirty files — skipping checkpoint")
            return None

        checkpoint_id = await self._checkpoint_mgr.create_checkpoint(dirty, deleted)
        self._dirty_tracker.clear()
        return checkpoint_id

    async def publish(self, artifacts: list[ArtifactSpec]) -> list[Artifact]:
        """Publish artifacts to the durable store.

        Args:
            artifacts: List of artifact specs to publish.

        Returns:
            List of published artifact metadata.
        """
        published: list[Artifact] = []
        for spec in artifacts:
            if not spec.publish:
                continue
            file_path = self.root / spec.path
            if not file_path.exists():
                logger.warning("Artifact not found for publish: %s", spec.path)
                continue
            data = file_path.read_bytes()
            artifact = await self._backend.publish_artifact(
                spec.path, data, content_type=spec.content_type
            )
            published.append(artifact)
            logger.info("Published artifact: %s → %s", spec.path, artifact.published_uri)
        return published

    async def close(self) -> None:
        """Close the workspace with multi-step drain.

        Sequence:
            1. Stop dirty tracker (no new events).
            2. Flush debouncer (force final checkpoint).
            3. Wait for uploader to drain.
            4. Close state store.
        """
        self._closing = True

        await self._dirty_tracker.stop()

        if self._debouncer is not None:
            await self._debouncer.flush()

        if self._uploader is not None:
            await self._uploader.stop()

        if self._state_store is not None:
            await self._state_store.close()

        logger.info("Workspace closed for run %s", self.run_id)

    async def cleanup(self) -> None:
        """Remove all workspace state and local files."""
        if self._state_store is not None:
            await self._state_store.cleanup()
        import shutil

        if self.root.exists():
            shutil.rmtree(self.root, ignore_errors=True)
        logger.info("Workspace cleaned up for run %s", self.run_id)

    async def recover(self) -> Manifest | None:
        """Recover workspace state from the latest checkpoint.

        Returns:
            The recovered manifest, or `None` if no checkpoints exist.
        """
        if self._checkpoint_mgr is None:
            return None
        return await self._checkpoint_mgr.recover()
