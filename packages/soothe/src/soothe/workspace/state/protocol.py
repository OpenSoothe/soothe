"""WorkspaceStateStore protocol — async interface for workspace-local state.

Tracks dirty files, blob cache index, checkpoint references, and artifact
metadata.  The state DB is a runtime cache; only the referenced blobs and
manifests in the object store are durable.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class WorkspaceStateStore(Protocol):
    """Async interface for workspace-local state.

    Implementations provide SQLite or PostgreSQL backends that track
    files, blobs, checkpoints, and artifacts for a single workspace run.
    """

    # -- file tracking ----------------------------------------------------

    async def upsert_file(
        self,
        path: str,
        *,
        size: int,
        mtime: float,
        inode: int | None,
        sha256: str | None,
        status: str,
    ) -> None:
        """Insert or update a file record.

        Args:
            path: Relative workspace path.
            size: File size in bytes.
            mtime: Modification timestamp (monotonic or epoch).
            inode: Inode number, or `None` if not available.
            sha256: Content hash, or `None` if not yet computed.
            status: File status — `'clean'`, `'dirty'`,
                `'rejected_symlink'`.
        """
        ...

    async def get_file(self, path: str) -> dict[str, Any] | None:
        """Get a file record by path.

        Args:
            path: Relative workspace path.

        Returns:
            File record dict, or `None` if not tracked.
        """
        ...

    async def list_dirty_files(self) -> list[dict[str, Any]]:
        """Return all files with `status='dirty'`.

        Returns:
            List of file record dicts.
        """
        ...

    async def clear_dirty(self) -> None:
        """Set all dirty files to `status='clean'`."""
        ...

    # -- blob cache index -------------------------------------------------

    async def upsert_blob(
        self,
        sha256: str,
        *,
        size: int,
        local_path: str,
        last_used: float,
    ) -> None:
        """Insert or update a blob cache entry.

        Args:
            sha256: Content hash.
            size: Blob size in bytes.
            local_path: Path in the local CAS cache.
            last_used: Timestamp of last access.
        """
        ...

    async def get_blob(self, sha256: str) -> dict[str, Any] | None:
        """Get a blob cache entry by hash.

        Args:
            sha256: Content hash.

        Returns:
            Blob record dict, or `None` if not cached.
        """
        ...

    # -- checkpoint references -------------------------------------------

    async def insert_checkpoint(
        self,
        checkpoint_id: str,
        *,
        manifest_hash: str | None,
        status: str,
    ) -> None:
        """Insert a checkpoint reference.

        Args:
            checkpoint_id: Unique checkpoint identifier.
            manifest_hash: Hash of the manifest at checkpoint time.
            status: `'pending_upload'` or `'uploaded'`.
        """
        ...

    async def list_pending_checkpoints(self) -> list[dict[str, Any]]:
        """Return checkpoints with `status='pending_upload'` in FIFO order.

        Returns:
            List of checkpoint record dicts.
        """
        ...

    async def update_checkpoint_status(
        self,
        checkpoint_id: str,
        status: str,
    ) -> None:
        """Update a checkpoint's status.

        Args:
            checkpoint_id: Checkpoint identifier.
            status: New status (`'uploaded'`, `'pending_upload'`).
        """
        ...

    # -- artifact tracking ------------------------------------------------

    async def upsert_artifact(
        self,
        path: str,
        *,
        sha256: str,
        published_uri: str | None,
        status: str,
    ) -> None:
        """Insert or update an artifact record.

        Args:
            path: Relative workspace path.
            sha256: Content hash.
            published_uri: URI in the object store, or `None`.
            status: `'pending'` or `'published'`.
        """
        ...

    # -- lifecycle --------------------------------------------------------

    async def close(self) -> None:
        """Close the underlying connection."""
        ...

    async def cleanup(self) -> None:
        """Remove all state for this workspace (used on workspace deletion)."""
        ...
