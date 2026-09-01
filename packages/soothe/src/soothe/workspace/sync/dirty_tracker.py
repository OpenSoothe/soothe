"""Dirty file tracking for workspace incremental persistence.

Hybrid platform-adaptive tracker: uses native OS watchers (inotify on
Linux, FSEvents on macOS) when available, falls back to stat-scan
polling otherwise.  Detects escaping symlinks via `os.lstat()` and
excludes them from checkpointing.
"""

from __future__ import annotations

import asyncio
import logging
import os
import stat
import sys
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable

logger = logging.getLogger(__name__)

_DEFAULT_POLL_INTERVAL = 2.0  # seconds

_EXCLUDED_DIRS = frozenset({".workspace", "__pycache__", ".git"})

_WATCHED_SUBDIRS = ("input", "working", "output")


class FileEventKind(StrEnum):
    """Type of filesystem event.

    Attributes:
        CREATE: A new file was created.
        MODIFY: An existing file was modified.
        DELETE: A file was deleted.
        MOVE: A file was moved/renamed.
    """

    CREATE = "create"
    MODIFY = "modify"
    DELETE = "delete"
    MOVE = "move"


class FileEvent:
    """A single filesystem event for a dirty file.

    Attributes:
        kind: Event type (create, modify, delete, move).
        mtime: File modification time (epoch seconds).
        size: File size in bytes.
        status: Tracking status — `dirty` (normal) or
            `rejected_symlink` (escaping symlink, excluded from
            checkpointing).
    """

    __slots__ = ("kind", "mtime", "size", "status")

    def __init__(
        self,
        *,
        kind: FileEventKind,
        mtime: float = 0.0,
        size: int = 0,
        status: str = "dirty",
    ) -> None:
        self.kind = kind
        self.mtime = mtime
        self.size = size
        self.status = status

    def __repr__(self) -> str:
        return (
            f"FileEvent(kind={self.kind.value!r}, mtime={self.mtime:.1f}, "
            f"size={self.size}, status={self.status!r})"
        )


class DirtyTracker:
    """Hybrid platform-adaptive dirty file tracker.

    Watches `input/`, `working/`, and `output/` directories under
    `workspace_root`.  On platforms with native watchers, uses them;
    otherwise falls back to stat-scan polling.

    Args:
        workspace_root: The agent workspace root directory.
        poll_interval: Stat-scan poll interval in seconds (fallback
            mode).  Must be ≤ the debounce window.
        on_dirty: Optional callback invoked when the dirty set changes.
            Called with no arguments.

    Example:
        >>> tracker = DirtyTracker(workspace_root="/ws/run-1")
        >>> tracker.start()
        >>> # ... agent writes files ...
        >>> dirty = tracker.get_dirty()
    """

    def __init__(
        self,
        *,
        workspace_root: str | Path,
        poll_interval: float = _DEFAULT_POLL_INTERVAL,
        on_dirty: Callable[[], None] | None = None,
    ) -> None:
        self._root = Path(workspace_root).resolve()
        self._poll_interval = poll_interval
        self._on_dirty = on_dirty
        self._dirty_files: dict[str, FileEvent] = {}
        self._deleted_files: set[str] = set()
        self._running = False
        self._task: asyncio.Task[None] | None = None
        self._native_available = _detect_native_watcher()
        self._baseline: dict[str, tuple[float, int]] = {}

    @property
    def dirty_files(self) -> dict[str, FileEvent]:
        """Return the current dirty files dict (path → event)."""
        return dict(self._dirty_files)

    @property
    def deleted_files(self) -> set[str]:
        """Return the set of deleted file paths."""
        return set(self._deleted_files)

    @property
    def is_native(self) -> bool:
        """Return whether a native watcher is available."""
        return self._native_available

    def start(self) -> None:
        """Start tracking filesystem mutations.

        Takes a baseline snapshot of the workspace, then begins polling
        (or native watching if available).
        """
        if self._running:
            return
        self._running = True
        self._baseline = self._scan_workspace()
        logger.info(
            "DirtyTracker started: root=%s, native=%s, baseline_files=%d",
            self._root,
            self._native_available,
            len(self._baseline),
        )

        if not self._native_available:
            self._task = asyncio.create_task(self._poll_loop())

    async def stop(self) -> None:
        """Stop tracking and clean up."""
        self._running = False
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        logger.info(
            "DirtyTracker stopped: dirty=%d, deleted=%d",
            len(self._dirty_files),
            len(self._deleted_files),
        )

    def mark_dirty(self, relative_path: str, *, kind: FileEventKind | None = None) -> None:
        """Manually mark a file as dirty.

        Args:
            relative_path: Workspace-relative path of the file.
            kind: Event kind.  If `None`, inferred from file existence.
        """
        full_path = self._root / relative_path

        # Use lstat to detect symlinks without following them.
        try:
            st = os.lstat(full_path)
        except FileNotFoundError:
            self._deleted_files.add(relative_path)
            self._dirty_files.pop(relative_path, None)
            if self._on_dirty:
                self._on_dirty()
            return

        if stat.S_ISLNK(st.st_mode):
            from soothe.workspace.sync.cas import is_symlink_escaping

            if is_symlink_escaping(full_path, self._root):
                logger.warning("Rejecting escaping symlink: %s", relative_path)
                self._dirty_files[relative_path] = FileEvent(
                    kind=kind or FileEventKind.MODIFY,
                    mtime=st.st_mtime,
                    size=st.st_size,
                    status="rejected_symlink",
                )
                if self._on_dirty:
                    self._on_dirty()
                return

        if kind is None:
            kind = (
                FileEventKind.CREATE
                if relative_path not in self._baseline
                else FileEventKind.MODIFY
            )

        self._dirty_files[relative_path] = FileEvent(
            kind=kind,
            mtime=st.st_mtime,
            size=st.st_size,
        )
        self._deleted_files.discard(relative_path)
        if self._on_dirty:
            self._on_dirty()

    def clear(self) -> None:
        """Clear all dirty and deleted state (after a checkpoint)."""
        self._dirty_files.clear()
        self._deleted_files.clear()

    def get_dirty(self) -> dict[str, FileEvent]:
        """Return dirty files that are not rejected symlinks."""
        return {
            path: event
            for path, event in self._dirty_files.items()
            if event.status != "rejected_symlink"
        }

    def get_rejected(self) -> list[str]:
        """Return paths of rejected (escaping symlink) files."""
        return [
            path for path, event in self._dirty_files.items() if event.status == "rejected_symlink"
        ]

    # ------------------------------------------------------------------
    # Stat-scan polling
    # ------------------------------------------------------------------

    async def _poll_loop(self) -> None:
        """Background poll loop for stat-scan mode."""
        logger.info("DirtyTracker stat-scan polling started (interval=%ss)", self._poll_interval)
        while self._running:
            try:
                self._scan_and_diff()
            except Exception:
                logger.exception("Error in dirty tracker poll loop")
            await asyncio.sleep(self._poll_interval)

    def _scan_and_diff(self) -> None:
        """Scan workspace and diff against baseline/last scan."""
        current = self._scan_workspace()
        changed = False

        for path, (mtime, size) in current.items():
            prev = self._baseline.get(path)
            if prev is None or prev != (mtime, size):
                if path not in self._dirty_files:
                    kind = FileEventKind.CREATE if prev is None else FileEventKind.MODIFY
                    self._dirty_files[path] = FileEvent(kind=kind, mtime=mtime, size=size)
                    changed = True
                else:
                    event = self._dirty_files[path]
                    event.mtime = mtime
                    event.size = size

        for path in self._baseline:
            if path not in current and path not in self._deleted_files:
                self._deleted_files.add(path)
                self._dirty_files.pop(path, None)
                changed = True

        self._baseline = current

        if changed and self._on_dirty:
            self._on_dirty()

    def _scan_workspace(self) -> dict[str, tuple[float, int]]:
        """Scan the workspace and return a snapshot of file states.

        Returns:
            Dict of relative path → (mtime, size).
        """
        snapshot: dict[str, tuple[float, int]] = {}
        for subdir in _WATCHED_SUBDIRS:
            dirpath = self._root / subdir
            if not dirpath.exists():
                continue
            for root, dirs, files in os.walk(dirpath, followlinks=False):
                dirs[:] = [d for d in dirs if d not in _EXCLUDED_DIRS]
                for filename in files:
                    full = Path(root) / filename
                    try:
                        st = os.lstat(full)
                        rel = str(full.relative_to(self._root))
                        snapshot[rel] = (st.st_mtime, st.st_size)
                    except OSError:
                        pass
        return snapshot


# ---------------------------------------------------------------------------
# Platform detection
# ---------------------------------------------------------------------------


def _detect_native_watcher() -> bool:
    """Detect whether a native OS filesystem watcher is available.

    Returns:
        `True` if inotify (Linux) or FSEvents (macOS) is available.
        Currently returns `False` — the stat-scan poller is the MVP
        implementation.  Native watcher integration is a future
        optimization.
    """
    if sys.platform == "linux":
        try:
            import ctypes.util

            if ctypes.util.find_library("c"):
                return False  # MVP: don't use inotify yet
        except Exception:
            pass
    elif sys.platform == "darwin":
        return False  # MVP: don't use FSEvents yet
    return False
