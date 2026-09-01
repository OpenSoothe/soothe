"""Checkpoint lifecycle management — snapshot + delta, compaction, recovery.

First checkpoint of a run is a SNAPSHOT (full manifest + dirty set).
Subsequent checkpoints are DELTAs (only changed files, referencing parent).
Periodic compaction collapses the delta chain into a fresh SNAPSHOT when
delta count or cumulative dirty-file count exceeds thresholds.  Recovery
anchors on the latest SNAPSHOT and replays DELTAs forward.
"""

from __future__ import annotations

import hashlib
import logging
from typing import TYPE_CHECKING

from soothe_sdk.protocols.workspace_sync import (
    CheckpointPayload,
    CheckpointType,
    Manifest,
    ManifestEntry,
)

if TYPE_CHECKING:
    from pathlib import Path

    from soothe_sdk.protocols.workspace_sync import WorkspaceSyncBackend

    from soothe.workspace.sync.cas import CASCache
    from soothe.workspace.sync.dirty_tracker import DirtyTracker

logger = logging.getLogger(__name__)

_DEFAULT_MAX_DELTAS = 10
_DEFAULT_MAX_CUMULATIVE_DIRTY = 500


class CheckpointManager:
    """Manages the checkpoint lifecycle for a single workspace run.

    Creates snapshots and deltas, serializes them to `CheckpointPayload`
    JSON, and stores them via the `WorkspaceSyncBackend`.  Also handles
    compaction and crash recovery.

    Args:
        run_id: Unique run identifier.
        backend: Storage backend for remote persistence.
        cas: Local content-addressed storage cache.
        dirty_tracker: Dirty file tracker (source of dirty file paths).
        workspace_root: Local workspace root path.
        max_deltas: Compaction threshold — max delta chain length.
        max_cumulative_dirty: Compaction threshold — max cumulative
            dirty-file entries across the delta chain.
    """

    def __init__(
        self,
        *,
        run_id: str,
        backend: WorkspaceSyncBackend,
        cas: CASCache,
        dirty_tracker: DirtyTracker,
        workspace_root: Path,
        max_deltas: int = _DEFAULT_MAX_DELTAS,
        max_cumulative_dirty: int = _DEFAULT_MAX_CUMULATIVE_DIRTY,
    ) -> None:
        self._run_id = run_id
        self._backend = backend
        self._cas = cas
        self._dirty_tracker = dirty_tracker
        self._workspace_root = workspace_root
        self._max_deltas = max_deltas
        self._max_cumulative_dirty = max_cumulative_dirty
        self._checkpoint_seq = 0
        self._last_checkpoint_id: str | None = None
        self._last_snapshot_id: str | None = None
        self._delta_count = 0
        self._cumulative_dirty_count = 0
        self._manifest: Manifest | None = None

    @property
    def manifest(self) -> Manifest | None:
        """Return the current manifest (or `None` before first checkpoint)."""
        return self._manifest

    @property
    def last_checkpoint_id(self) -> str | None:
        """Return the ID of the most recent checkpoint."""
        return self._last_checkpoint_id

    async def initialize(self) -> None:
        """Load the existing manifest from the backend, if any.

        Called at workspace open to restore state from a prior run
        (crash recovery scenario).
        """
        self._manifest = await self._backend.get_manifest(self._run_id)
        if self._manifest is not None:
            checkpoints = await self._backend.list_checkpoints(self._run_id)
            if checkpoints:
                self._last_checkpoint_id = checkpoints[-1]
                self._checkpoint_seq = len(checkpoints)
                for ckpt_id in reversed(checkpoints):
                    data = await self._backend.get_checkpoint(ckpt_id)
                    if data is not None:
                        payload = CheckpointPayload.model_validate_json(data)
                        if payload.is_snapshot():
                            self._last_snapshot_id = ckpt_id
                            break
                if self._last_snapshot_id is not None:
                    snapshot_idx = checkpoints.index(self._last_snapshot_id)
                    self._delta_count = len(checkpoints) - snapshot_idx - 1
                else:
                    self._delta_count = len(checkpoints)
            logger.info(
                "Recovered run %s: %d checkpoints, last_snapshot=%s",
                self._run_id,
                len(checkpoints),
                self._last_snapshot_id,
            )

    async def create_checkpoint(self) -> str:
        """Create a checkpoint from the current dirty state.

        Decides whether to write a SNAPSHOT or DELTA based on the
        compaction thresholds.  Uploads dirty-file blobs to the backend,
        updates the manifest, and stores the checkpoint payload.

        Returns:
            The checkpoint ID (e.g. `"c001"`).
        """
        dirty = self._dirty_tracker.get_dirty()
        deleted = self._dirty_tracker.deleted_files

        dirty_entries: list[ManifestEntry] = []
        for rel_path, event in dirty.items():
            abs_path = self._workspace_root / rel_path
            if not abs_path.exists():
                deleted.add(rel_path)
                continue
            if abs_path.is_symlink():
                target = abs_path.resolve()
                try:
                    target.relative_to(self._workspace_root.resolve())
                except ValueError:
                    logger.warning(
                        "Skipping escaping symlink at checkpoint: %s -> %s",
                        rel_path,
                        target,
                    )
                    continue

            data = abs_path.read_bytes()
            sha256 = hashlib.sha256(data).hexdigest()
            if not await self._backend.head_blob(sha256):
                await self._backend.put_blob(sha256, data)
            if not self._cas.has_blob(sha256):
                self._cas.store_blob(sha256, data)
            dirty_entries.append(ManifestEntry(path=rel_path, sha256=sha256, size=len(data)))

        if self._manifest is None:
            self._manifest = Manifest(
                run_id=self._run_id,
                version=1,
                resources=[],
                artifacts=dirty_entries,
            )
        else:
            new_artifacts = {e.path: e for e in self._manifest.artifacts}
            for entry in dirty_entries:
                new_artifacts[entry.path] = entry
            for d in deleted:
                new_artifacts.pop(d, None)
            self._manifest = Manifest(
                run_id=self._run_id,
                version=self._manifest.version + 1,
                resources=self._manifest.resources,
                artifacts=list(new_artifacts.values()),
            )

        self._checkpoint_seq += 1
        checkpoint_id = f"c{self._checkpoint_seq:03d}"
        is_compaction = (
            self._delta_count >= self._max_deltas
            or self._cumulative_dirty_count >= self._max_cumulative_dirty
        )

        if self._last_checkpoint_id is None or is_compaction:
            payload = CheckpointPayload(
                checkpoint_id=checkpoint_id,
                kind=CheckpointType.SNAPSHOT,
                manifest_version=self._manifest.version,
                dirty_files=dirty_entries,
                manifest_snapshot=self._manifest,
                parent_checkpoint_id=None,
            )
            self._last_snapshot_id = checkpoint_id
            self._delta_count = 0
            self._cumulative_dirty_count = 0
            logger.info("Created SNAPSHOT checkpoint %s for run %s", checkpoint_id, self._run_id)
        else:
            payload = CheckpointPayload(
                checkpoint_id=checkpoint_id,
                kind=CheckpointType.DELTA,
                manifest_version=self._manifest.version,
                dirty_files=dirty_entries,
                manifest_snapshot=None,
                parent_checkpoint_id=self._last_checkpoint_id,
            )
            self._delta_count += 1
            self._cumulative_dirty_count += len(dirty_entries)
            logger.info("Created DELTA checkpoint %s for run %s", checkpoint_id, self._run_id)

        data = payload.model_dump_json().encode("utf-8")
        await self._backend.put_checkpoint(
            checkpoint_id=f"{self._run_id}-{checkpoint_id}",
            data=data,
        )

        await self._backend.put_manifest(
            self._run_id,
            self._manifest,
            if_match=str(self._manifest.version - 1) if self._manifest.version > 1 else None,
        )

        self._last_checkpoint_id = checkpoint_id

        self._dirty_tracker.clear()

        return checkpoint_id

    async def recover(self) -> CheckpointPayload | None:
        """Recover the latest checkpoint state.

        1. List checkpoints, find the latest SNAPSHOT.
        2. Deserialize and replay subsequent DELTAs.
        3. Return the final checkpoint payload.

        Returns:
            The recovered checkpoint payload, or `None` if no
            checkpoints exist.
        """
        checkpoints = await self._backend.list_checkpoints(self._run_id)
        if not checkpoints:
            return None

        snapshot_data: bytes | None = None
        snapshot_id: str | None = None
        snapshot_idx = 0
        for i, ckpt_id in enumerate(reversed(checkpoints)):
            data = await self._backend.get_checkpoint(ckpt_id)
            if data is None:
                continue
            payload = CheckpointPayload.model_validate_json(data)
            if payload.is_snapshot():
                snapshot_data = data
                snapshot_id = ckpt_id
                snapshot_idx = len(checkpoints) - 1 - i
                break

        if snapshot_data is None:
            logger.warning("No snapshot found for run %s; cannot recover", self._run_id)
            return None

        snapshot_payload = CheckpointPayload.model_validate_json(snapshot_data)
        logger.info("Recovery anchored on snapshot %s", snapshot_id)

        manifest = snapshot_payload.manifest_snapshot
        dirty_files = list(snapshot_payload.dirty_files)

        for ckpt_id in checkpoints[snapshot_idx + 1 :]:
            data = await self._backend.get_checkpoint(ckpt_id)
            if data is None:
                logger.warning("Missing delta %s during recovery; stopping", ckpt_id)
                break
            delta = CheckpointPayload.model_validate_json(data)
            dirty_paths = {e.path for e in delta.dirty_files}
            dirty_files = [e for e in dirty_files if e.path not in dirty_paths]
            dirty_files.extend(delta.dirty_files)

        if manifest is not None:
            self._manifest = manifest
            self._checkpoint_seq = len(checkpoints)
            self._last_checkpoint_id = checkpoints[-1]
            self._last_snapshot_id = snapshot_id
            self._delta_count = len(checkpoints) - snapshot_idx - 1

        return CheckpointPayload(
            checkpoint_id=checkpoints[-1],
            kind=CheckpointType.SNAPSHOT,
            manifest_version=manifest.version if manifest else 0,
            dirty_files=dirty_files,
            manifest_snapshot=manifest,
            parent_checkpoint_id=None,
        )
