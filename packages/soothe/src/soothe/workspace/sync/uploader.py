"""Background uploader with backpressure.

Drains pending checkpoints from the state store and pushes them to the
remote backend.  Checkpoints are written to the state DB with
`status='pending_upload'` before the uploader attempts the push (local
durability).  FIFO ordering; backpressure feedback to the debouncer when
pending count exceeds the threshold.  On startup, scans for pending
rows and re-attempts (crash recovery).
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any, Protocol

if TYPE_CHECKING:
    from soothe_sdk.protocols.workspace_sync import WorkspaceSyncBackend

logger = logging.getLogger(__name__)


class PendingCheckpointStore(Protocol):
    """Protocol for querying pending checkpoints from the state store."""

    async def list_pending_checkpoints(self) -> list[dict[str, Any]]:
        """Return pending checkpoints in FIFO order."""
        ...

    async def update_checkpoint_status(self, checkpoint_id: str, status: str) -> None:
        """Update the status of a checkpoint."""
        ...


class BackgroundUploader:
    """Background task that drains pending checkpoints to the remote backend.

    Args:
        backend: Remote storage backend.
        store: State store for pending checkpoint queries.
        max_pending: Backpressure threshold.  When exceeded, the
            `on_backpressure` callback is invoked.
        poll_interval: Seconds between drain cycles.
        on_backpressure: Optional callback invoked when pending count
            exceeds `max_pending`.  The debouncer uses this to increase
            the debounce window.
    """

    def __init__(
        self,
        *,
        backend: WorkspaceSyncBackend,
        store: PendingCheckpointStore,
        max_pending: int = 20,
        poll_interval: float = 2.0,
        on_backpressure: Any = None,
    ) -> None:
        self._backend = backend
        self._store = store
        self._max_pending = max_pending
        self._poll_interval = poll_interval
        self._on_backpressure = on_backpressure
        self._task: asyncio.Task[None] | None = None
        self._running = False
        self._closing = False

    @property
    def is_running(self) -> bool:
        """Return `True` if the upload loop is active."""
        return self._running

    @property
    def is_closing(self) -> bool:
        """Return `True` if the uploader is in shutdown (draining)."""
        return self._closing

    def start(self) -> None:
        """Start the background upload loop."""
        if self._running:
            return
        self._running = True
        self._closing = False
        self._task = asyncio.create_task(self._upload_loop())
        logger.info("Background uploader started: max_pending=%d", self._max_pending)

    async def stop(self) -> None:
        """Stop the uploader after draining pending checkpoints.

        Sets `_closing=True` (no new checkpoints accepted), waits for
        the upload loop to drain the queue, then shuts down.
        """
        if not self._running:
            return
        self._closing = True
        if self._task is not None:
            try:
                await asyncio.wait_for(self._task, timeout=30.0)
            except TimeoutError:
                logger.warning("Background uploader drain timed out after 30s")
                if self._task:
                    self._task.cancel()
        self._running = False
        self._closing = False
        logger.info("Background uploader stopped")

    async def _upload_loop(self) -> None:
        """Main upload loop — drain pending checkpoints."""
        while self._running or self._closing:
            try:
                pending = await self._store.list_pending_checkpoints()

                if len(pending) > self._max_pending and self._on_backpressure:
                    self._on_backpressure(len(pending))

                if not pending:
                    if self._closing:
                        break
                    await asyncio.sleep(self._poll_interval)
                    continue

                all_processed = True
                for item in pending:
                    if not self._running and not self._closing:
                        break
                    success = await self._upload_one(item)
                    if not success:
                        all_processed = False

                if self._closing:
                    break

                if not all_processed:
                    await asyncio.sleep(self._poll_interval)

            except Exception:
                logger.exception("Error in background upload loop")
                await asyncio.sleep(self._poll_interval)

    async def _upload_one(self, item: dict[str, Any]) -> bool:
        """Upload a single pending checkpoint.

        Args:
            item: Pending checkpoint dict with keys like `checkpoint_id`,
                `data`, `manifest`.

        Returns:
            `True` if the upload succeeded, `False` on failure.
        """
        checkpoint_id: str = item["checkpoint_id"]
        data: bytes = item["data"]
        manifest = item.get("manifest")

        try:
            await self._backend.put_checkpoint(checkpoint_id, data, manifest)
            await self._store.update_checkpoint_status(checkpoint_id, "uploaded")
            logger.debug("Uploaded checkpoint %s", checkpoint_id)
            return True
        except Exception:
            logger.exception("Failed to upload checkpoint %s; will retry", checkpoint_id)
            return False
