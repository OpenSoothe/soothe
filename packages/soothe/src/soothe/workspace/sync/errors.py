"""Workspace sync error hierarchy.

Raised by the `FsspecSyncBackend` and the workspace manager to signal
integrity violations, concurrency conflicts, and general sync failures.
"""

from __future__ import annotations


class WorkspaceSyncError(Exception):
    """Base exception for workspace sync operations."""


class IntegrityError(WorkspaceSyncError):
    """Content hash mismatch detected during blob storage or retrieval.

    Raised when `put_blob` receives data whose SHA-256 does not match
    the declared hash, or when a CAS cache hit's stored content does
    not match its key.
    """


class ConcurrentModificationError(WorkspaceSyncError):
    """Optimistic concurrency conflict on manifest write.

    Raised by `put_manifest(if_match=...)` when the stored manifest
    version does not match the expected version, indicating another
    writer has modified the manifest since it was last read.
    """
