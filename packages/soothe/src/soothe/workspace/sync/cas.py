"""Local content-addressed storage (CAS) cache.

Stores immutable blobs keyed by SHA-256.  Shared across runs on the same
host so repeated materialization of the same blob requires zero object-
data bandwidth.  Materialization uses reflink → hardlink → copy fallback.
"""

from __future__ import annotations

import hashlib
import logging
import os
import stat
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING

from soothe.workspace.sync.paths import validate_path_component

if TYPE_CHECKING:
    from soothe_sdk.protocols.workspace_sync import WorkspaceSyncBackend

logger = logging.getLogger(__name__)

_COPY_CHUNK_SIZE = 1024 * 1024  # 1 MiB


class LinkStrategy(StrEnum):
    """Materialization strategy for placing a CAS blob into the workspace.

    Attributes:
        REFLINK: Copy-on-write reflink.  Preferred when source and
            destination are on the same filesystem.
        HARDLINK: Hard link.  Shares the same inode; the workspace copy
            is the working copy (the CAS blob is immutable).
        COPY: Full byte copy.  Always works, but wastes disk space.
    """

    REFLINK = "reflink"
    HARDLINK = "hardlink"
    COPY = "copy"


class CASCache:
    """Local content-addressed storage cache for workspace blobs.

    Immutable blobs are stored under `blobs/sha256/<first-2>/<hash>`.
    Shared across all runs on the same host.

    Args:
        cache_root: Directory where the CAS cache lives.

    Example:
        >>> cache = CASCache(cache_root="/data/agent-cache")
        >>> path = cache.store_blob("abc123...", b"hello")
    """

    def __init__(self, cache_root: str | Path) -> None:
        self._root = Path(cache_root)
        self._blobs_dir = self._root / "blobs" / "sha256"
        self._blobs_dir.mkdir(parents=True, exist_ok=True)
        self._link_strategy = _probe_link_strategy(self._root)
        logger.info(
            "CASCache initialized: root=%s, link_strategy=%s",
            self._root,
            self._link_strategy,
        )

    @property
    def root(self) -> Path:
        """Return the cache root directory."""
        return self._root

    @property
    def link_strategy(self) -> LinkStrategy:
        """Return the probed materialization strategy."""
        return self._link_strategy

    def blob_path(self, sha256: str) -> Path:
        """Return the local filesystem path for a blob.

        Args:
            sha256: Content hash (validated for path safety).

        Returns:
            `<root>/blobs/sha256/<first-2>/<hash>`
        """
        validate_path_component(sha256, name="sha256")
        return self._blobs_dir / sha256[:2] / sha256

    def has_blob(self, sha256: str) -> bool:
        """Return whether a blob is present in the local CAS cache."""
        path = self.blob_path(sha256)
        return path.is_file()

    def store_blob(self, sha256: str, data: bytes) -> Path:
        """Store raw bytes in the CAS cache under their content hash.

        Atomic write (write to temp, then rename).  Idempotent — no-op
        if the blob already exists.

        Args:
            sha256: Expected content hash (validated).
            data: Raw blob content.

        Returns:
            Path to the stored blob.

        Raises:
            IntegrityError: If the actual SHA-256 of `data` does not
                match `sha256`.
        """
        from soothe.workspace.sync.errors import IntegrityError

        validate_path_component(sha256, name="sha256")

        actual_hash = hashlib.sha256(data).hexdigest()
        if actual_hash != sha256:
            raise IntegrityError(
                f"CAS store hash mismatch: expected {sha256[:16]}..., got {actual_hash[:16]}..."
            )

        path = self.blob_path(sha256)
        if path.exists():
            return path  # idempotent

        path.parent.mkdir(parents=True, exist_ok=True)

        tmp_path = path.with_suffix(".tmp")
        try:
            tmp_path.write_bytes(data)
            os.replace(tmp_path, path)
        except Exception:
            tmp_path.unlink(missing_ok=True)
            raise

        logger.debug("CAS stored blob: %s (%d bytes)", sha256[:12], len(data))
        return path

    def materialize(
        self,
        sha256: str,
        dest: str | Path,
    ) -> Path:
        """Materialize a CAS blob to a workspace path.

        Uses the probed link strategy (reflink → hardlink → copy).
        Creates the destination's parent directory if needed.

        Args:
            sha256: Content hash of the blob to materialize.
            dest: Destination path in the workspace.

        Returns:
            The destination `Path`.

        Raises:
            FileNotFoundError: If the blob is not in the CAS cache.
        """
        src = self.blob_path(sha256)
        if not src.exists():
            raise FileNotFoundError(f"CAS blob not found: {sha256[:12]}")

        dest_path = Path(dest)
        dest_path.parent.mkdir(parents=True, exist_ok=True)

        # If dest is a symlink, remove it (don't follow it).
        if dest_path.is_symlink():
            dest_path.unlink()

        if self._link_strategy is LinkStrategy.REFLINK:
            _reflink_or_copy(src, dest_path)
        elif self._link_strategy is LinkStrategy.HARDLINK:
            try:
                os.link(src, dest_path)
            except OSError:
                _copy_file(src, dest_path)
        else:
            _copy_file(src, dest_path)

        logger.debug(
            "CAS materialized: %s → %s (%s)",
            sha256[:12],
            dest_path,
            self._link_strategy,
        )
        return dest_path

    async def fetch_and_cache(
        self,
        sha256: str,
        backend: WorkspaceSyncBackend,
    ) -> Path | None:
        """Download a blob from the remote backend and cache it locally.

        Cache hit returns immediately.  On miss, downloads, verifies hash,
        and stores in the CAS cache.

        Args:
            sha256: Content hash to fetch.
            backend: Remote storage backend.

        Returns:
            Path to the cached blob, or `None` if the backend does not
            have the blob.
        """
        if self.has_blob(sha256):
            logger.debug("CAS cache hit: %s", sha256[:12])
            return self.blob_path(sha256)

        data = await backend.get_blob(sha256)
        if data is None:
            return None

        return self.store_blob(sha256, data)

    def remove_blob(self, sha256: str) -> None:
        """Remove a blob from the CAS cache."""
        path = self.blob_path(sha256)
        path.unlink(missing_ok=True)

    def close(self) -> None:
        """No-op — the CAS cache uses the filesystem, no resources to close."""
        pass


# ---------------------------------------------------------------------------
# Filesystem capability probing
# ---------------------------------------------------------------------------


def _probe_link_strategy(cache_root: Path) -> LinkStrategy:
    """Probe the best available materialization strategy.

    Tests reflink first, then hardlink, then falls back to copy.

    Args:
        cache_root: The CAS cache root directory.

    Returns:
        The best available `LinkStrategy`.
    """
    src = cache_root / f".probe-{os.getpid()}.src"
    dst = cache_root / f".probe-{os.getpid()}.dst"

    try:
        src.write_bytes(b"probe")
        dst.unlink(missing_ok=True)

        if _try_reflink(src, dst):
            return LinkStrategy.REFLINK

        dst.unlink(missing_ok=True)

        try:
            os.link(src, dst)
            return LinkStrategy.HARDLINK
        except OSError:
            pass

        return LinkStrategy.COPY
    finally:
        src.unlink(missing_ok=True)
        dst.unlink(missing_ok=True)


def _try_reflink(src: Path, dst: Path) -> bool:
    """Attempt a reflink (copy-on-write) from src to dst.

    Returns `True` on success, `False` if reflink is not supported.
    """
    if _try_reflink_darwin(src, dst):
        return True

    if _try_reflink_linux(src, dst):
        return True

    return False


def _try_reflink_darwin(src: Path, dst: Path) -> bool:
    """Attempt macOS clonefile(2) via ctypes."""
    try:
        import ctypes.util

        libc = ctypes.CDLL(ctypes.util.find_library("c"), use_errno=True)

        clone_nofollow = 0x0001
        result = libc.clonefile(
            str(src).encode("utf-8"),
            str(dst).encode("utf-8"),
            clone_nofollow,
        )
        if result == 0:
            return True
        return False
    except Exception:
        return False


def _try_reflink_linux(src: Path, dst: Path) -> bool:
    """Attempt Linux FICLONE ioctl via fcntl."""
    try:
        import fcntl

        ficlone = 0x40049409

        with open(src, "rb") as src_fd, open(dst, "wb") as dst_fd:
            result = fcntl.ioctl(dst_fd.fileno(), ficlone, src_fd.fileno())
            if result == 0:
                return True
        return False
    except Exception:
        Path(dst).unlink(missing_ok=True)
        return False


def _reflink_or_copy(src: Path, dst: Path) -> None:
    """Try reflink, fall back to copy."""
    if not _try_reflink(src, dst):
        _copy_file(src, dst)


def _copy_file(src: Path, dst: Path) -> None:
    """Copy file contents in chunks."""
    with open(src, "rb") as fsrc, open(dst, "wb") as fdst:
        while True:
            chunk = fsrc.read(_COPY_CHUNK_SIZE)
            if not chunk:
                break
            fdst.write(chunk)


# ---------------------------------------------------------------------------
# Symlink security
# ---------------------------------------------------------------------------


def is_symlink_escaping(path: str | Path, workspace_root: str | Path) -> bool:
    """Check whether a path is a symlink whose target escapes the workspace.

    Uses `os.lstat()` to detect symlinks without following them.  If the
    symlink target resolves outside the workspace root, returns `True`.

    Args:
        path: The file path to check.
        workspace_root: The workspace root directory.

    Returns:
        `True` if the path is an escaping symlink.
    """
    p = Path(path)
    if not p.is_symlink():
        return False

    workspace_root = Path(workspace_root).resolve()
    try:
        target = p.resolve(strict=False)
    except OSError:
        return True  # unresolvable symlink → treat as escaping

    try:
        target.relative_to(workspace_root)
        return False  # target is inside workspace
    except ValueError:
        return True  # target escapes workspace


def scan_escaping_symlinks(directory: str | Path, workspace_root: str | Path) -> list[Path]:
    """Scan a directory tree for symlinks escaping the workspace root.

    Args:
        directory: Directory to scan recursively.
        workspace_root: The workspace root directory.

    Returns:
        List of symlink paths whose targets escape the workspace.
    """
    escaping: list[Path] = []
    root = Path(workspace_root).resolve()

    for dirpath, dirnames, filenames in os.walk(directory, followlinks=False):
        for name in dirnames + filenames:
            full = Path(dirpath) / name
            try:
                st = os.lstat(full)
            except OSError:
                continue
            if stat.S_ISLNK(st.st_mode):
                try:
                    target = full.resolve(strict=False)
                    target.relative_to(root)
                except (ValueError, OSError):
                    escaping.append(full)

    return escaping
