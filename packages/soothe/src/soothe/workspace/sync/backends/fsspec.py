"""Concrete `WorkspaceSyncBackend` backed by any fsspec filesystem.

One adapter supports S3 (`s3fs`), GCS (`gcsfs`), Azure Blob (`adlfs`),
local, and memory filesystems.  All fsspec calls are offloaded to a
dedicated thread pool via `asyncio.to_thread()`.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
from concurrent.futures import ThreadPoolExecutor
from typing import TYPE_CHECKING, Any

from soothe_sdk.protocols.workspace_sync import (
    Artifact,
    Manifest,
)

from soothe.workspace.sync.errors import ConcurrentModificationError, IntegrityError
from soothe.workspace.sync.paths import validate_path_component, validate_relative_path

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

logger = logging.getLogger(__name__)

_DEFAULT_MAX_WORKERS = 8
_STREAM_CHUNK_SIZE = 65536  # 64 KiB


class FsspecSyncBackend:
    """`WorkspaceSyncBackend` backed by an fsspec `AbstractFileSystem`.

    Args:
        fs: An fsspec filesystem instance (e.g. `MemoryFileSystem`,
            `S3FileSystem`, `LocalFileSystem`).
        root: Root path within the filesystem where all workspace sync
            objects are stored.
        max_workers: Thread pool size for I/O offloading.

    Example:
        >>> backend = FsspecSyncBackend(fs=MemoryFileSystem(), root="/ws")
        >>> data = await backend.get_blob("abc123...")
    """

    def __init__(
        self,
        *,
        fs: Any,
        root: str,
        max_workers: int = _DEFAULT_MAX_WORKERS,
    ) -> None:
        self._fs = fs
        self._root = root.rstrip("/")
        self._executor = ThreadPoolExecutor(
            max_workers=max_workers,
            thread_name_prefix="fsspec-sync",
        )
        logger.debug(
            "FsspecSyncBackend initialized: root=%s, fs=%s, max_workers=%d",
            self._root,
            type(fs).__name__,
            max_workers,
        )

    # ------------------------------------------------------------------
    # Path-layout mapper
    # ------------------------------------------------------------------

    def _blob_path(self, sha256: str) -> str:
        """Map a content hash to its storage path."""
        validate_path_component(sha256, name="sha256")
        return f"{self._root}/blobs/sha256/{sha256[:2]}/{sha256}"

    def _manifest_path(self, run_id: str) -> str:
        """Map a run ID to its manifest storage path."""
        validate_path_component(run_id, name="run_id")
        return f"{self._root}/runs/{run_id}/manifest.json"

    def _checkpoint_dir(self, run_id: str) -> str:
        """Map a run ID to its checkpoint directory."""
        validate_path_component(run_id, name="run_id")
        return f"{self._root}/runs/{run_id}/checkpoints"

    def _checkpoint_path(self, checkpoint_id: str) -> str:
        """Map a checkpoint ID to its storage path."""
        validate_path_component(checkpoint_id, name="checkpoint_id")
        if "-" in checkpoint_id:
            run_id = checkpoint_id.rsplit("-", 1)[0]
            validate_path_component(run_id, name="checkpoint_id (run prefix)")
            seq = checkpoint_id.rsplit("-", 1)[1]
            validate_path_component(seq, name="checkpoint_id (sequence)")
        else:
            run_id = checkpoint_id
        return f"{self._root}/runs/{run_id}/checkpoints/{checkpoint_id}.json"

    def _artifact_storage_path(self, artifact_path: str) -> str:
        """Map an artifact relative path to its storage path."""
        validated = validate_relative_path(artifact_path, name="artifact_path")
        return f"{self._root}/artifacts/{validated}"

    # ------------------------------------------------------------------
    # Thread-pool helper
    # ------------------------------------------------------------------

    async def _to_thread(self, fn: Any, *args: Any, **kwargs: Any) -> Any:
        """Run a sync function in the dedicated thread pool."""
        return await asyncio.get_event_loop().run_in_executor(
            self._executor, lambda: fn(*args, **kwargs)
        )

    # ------------------------------------------------------------------
    # Blob operations (content-addressed)
    # ------------------------------------------------------------------

    async def get_blob(self, sha256: str) -> bytes | None:
        """Return blob content by hash, or `None` if absent."""
        path = self._blob_path(sha256)
        try:
            return await self._to_thread(self._fs.cat, path)
        except FileNotFoundError:
            return None

    async def put_blob(self, sha256: str, data: bytes) -> None:
        """Store a blob.  Idempotent — no-op if the hash already exists.

        Verifies content hash before storing.

        Raises:
            IntegrityError: If `data`'s actual SHA-256 does not match
                `sha256`.
        """
        validate_path_component(sha256, name="sha256")
        actual_hash = hashlib.sha256(data).hexdigest()
        if actual_hash != sha256:
            raise IntegrityError(
                f"content hash mismatch for blob {sha256[:8]!r}: "
                f"expected {sha256[:16]}..., got {actual_hash[:16]}..."
            )

        path = self._blob_path(sha256)
        exists = await self._to_thread(self._fs.exists, path)
        if exists:
            return  # idempotent — blob already stored
        await self._to_thread(self._fs.pipe, path, data)

    async def head_blob(self, sha256: str) -> bool:
        """Return whether a blob with this hash exists remotely."""
        path = self._blob_path(sha256)
        return await self._to_thread(self._fs.exists, path)

    # ------------------------------------------------------------------
    # Manifest operations (optimistic concurrency)
    # ------------------------------------------------------------------

    async def get_manifest(self, run_id: str) -> Manifest | None:
        """Fetch the latest manifest for `run_id`, or `None` if none exists."""
        path = self._manifest_path(run_id)
        try:
            data = await self._to_thread(self._fs.cat, path)
        except FileNotFoundError:
            return None
        return Manifest.model_validate_json(data)

    async def put_manifest(
        self,
        run_id: str,
        manifest: Manifest,
        *,
        if_match: str | None = None,
    ) -> Manifest:
        """Write or update the manifest for `run_id`.

        Args:
            run_id: Target run identifier.
            manifest: The manifest to write.
            if_match: If provided, reject the write when the stored
                manifest version does not match.

        Returns:
            The written manifest.

        Raises:
            ConcurrentModificationError: If `if_match` is provided and
                the stored version does not match.
        """
        if if_match is not None:
            existing = await self.get_manifest(run_id)
            if existing is not None and str(existing.version) != str(if_match):
                raise ConcurrentModificationError(
                    f"manifest version mismatch for run {run_id!r}: "
                    f"expected {if_match}, found {existing.version}"
                )

        path = self._manifest_path(run_id)
        data = manifest.model_dump_json().encode("utf-8")
        await self._to_thread(self._fs.pipe, path, data)
        return manifest

    # ------------------------------------------------------------------
    # Checkpoint operations
    # ------------------------------------------------------------------

    async def list_checkpoints(self, run_id: str) -> list[str]:
        """Return checkpoint IDs for `run_id`, ordered oldest-first."""
        ckpt_dir = self._checkpoint_dir(run_id)
        try:
            entries = await self._to_thread(self._fs.ls, ckpt_dir)
        except FileNotFoundError:
            return []

        ids: list[str] = []
        for entry in entries:
            name = entry if isinstance(entry, str) else entry.get("name", "")
            if name.endswith(".json"):
                ckpt_id = name.rsplit("/", 1)[-1].removesuffix(".json")
                ids.append(ckpt_id)
        ids.sort()
        return ids

    async def get_checkpoint(self, checkpoint_id: str) -> bytes | None:
        """Fetch checkpoint payload by ID, or `None` if absent."""
        path = self._checkpoint_path(checkpoint_id)
        try:
            return await self._to_thread(self._fs.cat, path)
        except FileNotFoundError:
            return None

    async def put_checkpoint(
        self,
        checkpoint_id: str,
        data: bytes,
        manifest: Manifest | None = None,
    ) -> None:
        """Store a checkpoint payload.

        Args:
            checkpoint_id: Unique checkpoint identifier.
            data: Serialized checkpoint payload.
            manifest: Unused — the payload's `manifest_snapshot` field
                is preferred.
        """
        del manifest
        path = self._checkpoint_path(checkpoint_id)
        await self._to_thread(self._fs.pipe, path, data)

    # ------------------------------------------------------------------
    # Publish operations
    # ------------------------------------------------------------------

    async def publish_artifact(
        self,
        artifact_path: str,
        data: bytes,
        *,
        content_type: str | None = None,
    ) -> Artifact:
        """Publish an artifact to the durable store.

        Args:
            artifact_path: Relative workspace path of the artifact.
            data: Raw artifact content.
            content_type: MIME type hint (unused by fsspec).

        Returns:
            Published `Artifact` with SHA-256, size, and storage URI.
        """
        del content_type
        sha256 = hashlib.sha256(data).hexdigest()
        size = len(data)
        storage_path = self._artifact_storage_path(artifact_path)
        await self._to_thread(self._fs.pipe, storage_path, data)
        return Artifact(
            path=artifact_path,
            sha256=sha256,
            size=size,
            published_uri=storage_path,
        )

    # ------------------------------------------------------------------
    # Optional streaming (default impls buffer fully)
    # ------------------------------------------------------------------

    async def stream_blob(self, sha256: str) -> AsyncIterator[bytes]:
        """Stream blob content in 64 KiB chunks.

        Reads the entire blob in a single thread call, then yields from
        the buffer to avoid per-chunk thread submissions.
        """
        path = self._blob_path(sha256)
        try:
            data = await self._to_thread(self._fs.cat_file, path)
        except FileNotFoundError:
            return
        for offset in range(0, len(data), _STREAM_CHUNK_SIZE):
            yield data[offset : offset + _STREAM_CHUNK_SIZE]

    async def stream_checkpoint(self, checkpoint_id: str) -> AsyncIterator[bytes]:
        """Stream checkpoint content in 64 KiB chunks."""
        path = self._checkpoint_path(checkpoint_id)
        try:
            data = await self._to_thread(self._fs.cat_file, path)
        except FileNotFoundError:
            return
        for offset in range(0, len(data), _STREAM_CHUNK_SIZE):
            yield data[offset : offset + _STREAM_CHUNK_SIZE]

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def close(self) -> None:
        """Shut down the dedicated thread pool."""
        self._executor.shutdown(wait=False)

    async def __aenter__(self) -> FsspecSyncBackend:
        return self

    async def __aexit__(self, *args: object) -> None:
        self.close()
