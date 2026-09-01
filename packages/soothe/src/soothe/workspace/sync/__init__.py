"""Workspace sync subsystem — materialization, CAS, dirty tracking, checkpointing.

Host-side workspace sync layer.  The `WorkspaceSyncBackend` protocol and data
models live in `soothe-sdk`; this package provides the concrete
`FsspecSyncBackend` adapter, CAS cache, dirty tracker, debouncer, and
workspace manager.
"""

from soothe.workspace.sync.backends.fsspec import FsspecSyncBackend
from soothe.workspace.sync.cas import CASCache, LinkStrategy
from soothe.workspace.sync.checkpoint import CheckpointManager
from soothe.workspace.sync.debouncer import CheckpointDebouncer
from soothe.workspace.sync.dirty_tracker import DirtyTracker, FileEvent, FileEventKind
from soothe.workspace.sync.errors import (
    ConcurrentModificationError,
    IntegrityError,
    WorkspaceSyncError,
)
from soothe.workspace.sync.factory import construct_sync_backend
from soothe.workspace.sync.manager import WorkspaceManager
from soothe.workspace.sync.materializer import Materializer
from soothe.workspace.sync.uploader import BackgroundUploader
from soothe.workspace.sync.workspace import Workspace

__all__ = [
    "BackgroundUploader",
    "CASCache",
    "CheckpointDebouncer",
    "CheckpointManager",
    "ConcurrentModificationError",
    "DirtyTracker",
    "FsspecSyncBackend",
    "FileEvent",
    "FileEventKind",
    "IntegrityError",
    "LinkStrategy",
    "Materializer",
    "Workspace",
    "WorkspaceManager",
    "WorkspaceSyncError",
    "construct_sync_backend",
]
