"""Incremental materialization of resources from remote backend to workspace.

For each manifest entry: check local workspace state, check CAS cache, then
download from backend if needed.  Repeated materialization of an unchanged
resource requires zero object-data bandwidth — only the manifest is fetched.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
from pathlib import Path
from typing import TYPE_CHECKING

from soothe.workspace.sync.cas import CASCache, is_symlink_escaping, scan_escaping_symlinks
from soothe.workspace.sync.paths import validate_relative_path

if TYPE_CHECKING:
    from soothe_sdk.protocols.workspace_sync import Manifest, ManifestEntry, WorkspaceSyncBackend

logger = logging.getLogger(__name__)

_MAX_CONCURRENT_DOWNLOADS = 8


class Materializer:
    """Materializes resources from a remote backend into a local workspace.

    Args:
        backend: Remote storage backend.
        cas: Local content-addressed storage cache.
        workspace_root: The agent workspace root directory.  Resources
            are materialized under `<root>/input/`.
    """

    def __init__(
        self,
        *,
        backend: WorkspaceSyncBackend,
        cas: CASCache,
        workspace_root: str | Path,
    ) -> None:
        self._backend = backend
        self._cas = cas
        self._root = Path(workspace_root)

    async def materialize(self, manifest: Manifest) -> list[str]:
        """Materialize all resources from a manifest into the workspace.

        For each resource entry:
        1. Validate the path.
        2. Skip if the workspace file already has the correct hash.
        3. Link from CAS if the blob is cached.
        4. Download from backend, verify hash, store in CAS, materialize.

        Args:
            manifest: The resource manifest to materialize.

        Returns:
            List of resource paths that were materialized (downloaded or
            linked).  Skipped resources are not included.
        """
        self._remove_escaping_symlinks()

        materialized: list[str] = []
        semaphore = asyncio.Semaphore(_MAX_CONCURRENT_DOWNLOADS)

        async def _materialize_one(entry: ManifestEntry) -> str | None:
            async with semaphore:
                return await self._materialize_entry(entry)

        tasks = [_materialize_one(entry) for entry in manifest.resources]
        results = await asyncio.gather(*tasks)
        for path, was_materialized in zip(manifest.resources, results, strict=True):
            if was_materialized:
                materialized.append(path.path)

        return materialized

    async def _materialize_entry(self, entry: ManifestEntry) -> bool:
        """Materialize a single manifest entry.

        Returns `True` if the resource was materialized (downloaded or
        linked from CAS), `False` if it was already present with the
        correct hash.
        """
        validated = validate_relative_path(entry.path, name="resource_path")
        dest = self._root / "input" / validated

        # Skip if the workspace file already has the correct hash.
        if dest.is_file() and not dest.is_symlink():
            existing_hash = await asyncio.to_thread(_hash_file, dest)
            if existing_hash == entry.sha256:
                logger.debug("Materialize skip (already correct): %s", entry.path)
                return False

        # Remove escaping symlink if present.
        if dest.is_symlink():
            if is_symlink_escaping(dest, self._root):
                logger.warning("Removing escaping symlink: %s", dest)
                dest.unlink()
            else:
                dest.unlink()

        # Check CAS cache.
        if self._cas.has_blob(entry.sha256):
            self._cas.materialize(entry.sha256, dest)
            logger.debug("Materialized from CAS: %s", entry.path)
            return True

        # Download from backend.
        blob_path = await self._cas.fetch_and_cache(entry.sha256, self._backend)
        if blob_path is None:
            logger.error("Resource not found in backend: %s (%s)", entry.path, entry.sha256[:12])
            raise FileNotFoundError(
                f"Resource {entry.path!r} (hash {entry.sha256[:12]}...) not found in backend"
            )

        self._cas.materialize(entry.sha256, dest)
        logger.info("Materialized from backend: %s (%d bytes)", entry.path, entry.size)
        return True

    def _remove_escaping_symlinks(self) -> None:
        """Remove symlinks escaping the workspace root.

        Scans `input/`, `working/`, and `output/` directories for symlinks
        whose targets resolve outside the workspace root.
        """
        for subdir in ("input", "working", "output"):
            dirpath = self._root / subdir
            if not dirpath.exists():
                continue
            escaping = scan_escaping_symlinks(dirpath, self._root)
            for link in escaping:
                logger.warning("Removing escaping symlink: %s", link)
                link.unlink(missing_ok=True)


def _hash_file(path: str | Path) -> str:
    """Compute SHA-256 hex digest of a file's contents.

    Args:
        path: File path.

    Returns:
        Hex-encoded SHA-256 digest.
    """
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            chunk = f.read(1024 * 1024)  # 1 MiB
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()
