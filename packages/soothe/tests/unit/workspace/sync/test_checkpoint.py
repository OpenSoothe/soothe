"""Tests for the checkpoint manager — snapshot/delta, compaction, recovery.

Tests verify:
    - First checkpoint is a SNAPSHOT.
    - Subsequent checkpoints are DELTAs.
    - Compaction triggers a new SNAPSHOT after max_deltas.
    - Recovery anchors on the latest snapshot and replays deltas.
    - Dirty file blobs are uploaded to the backend.
    - Manifest is updated with correct version.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from fsspec.implementations.memory import MemoryFileSystem
from soothe_sdk.protocols.workspace_sync import (
    CheckpointType,
)

from soothe.workspace.sync.backends.fsspec import FsspecSyncBackend
from soothe.workspace.sync.cas import CASCache
from soothe.workspace.sync.checkpoint import CheckpointManager
from soothe.workspace.sync.dirty_tracker import DirtyTracker

if TYPE_CHECKING:
    pass


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

ROOT = "/test-checkpoint"


@pytest.fixture
def fs() -> MemoryFileSystem:
    """Fresh in-memory filesystem."""
    mem = MemoryFileSystem()
    yield mem
    try:
        mem.rm(ROOT, recursive=True)
    except FileNotFoundError:
        pass
    mem.store.clear()


@pytest.fixture
def backend(fs: MemoryFileSystem) -> FsspecSyncBackend:
    """Fresh backend instance."""
    b = FsspecSyncBackend(fs=fs, root=ROOT, max_workers=2)
    yield b
    b.close()


@pytest.fixture
def workspace_dir(tmp_path: Path) -> Path:
    """Temporary workspace with input/working/output dirs."""
    d = tmp_path / "workspace"
    for subdir in ("input", "working", "output"):
        (d / subdir).mkdir(parents=True)
    return d


@pytest.fixture
def cas(tmp_path: Path) -> CASCache:
    """Fresh CAS cache."""
    return CASCache(cache_root=tmp_path / "cas")


@pytest.fixture
def tracker(workspace_dir: Path) -> DirtyTracker:
    """Fresh dirty tracker (not started — used for manual mark_dirty)."""
    return DirtyTracker(workspace_root=workspace_dir)


@pytest.fixture
def manager(
    backend: FsspecSyncBackend,
    cas: CASCache,
    tracker: DirtyTracker,
    workspace_dir: Path,
) -> CheckpointManager:
    """Fresh checkpoint manager."""
    return CheckpointManager(
        run_id="run-123",
        backend=backend,
        cas=cas,
        dirty_tracker=tracker,
        workspace_root=workspace_dir,
        max_deltas=3,
        max_cumulative_dirty=100,
    )


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


# ---------------------------------------------------------------------------
# Checkpoint creation
# ---------------------------------------------------------------------------


class TestCheckpointCreation:
    """Tests for snapshot/delta checkpoint creation."""

    @pytest.mark.asyncio
    async def test_first_checkpoint_is_snapshot(
        self, manager: CheckpointManager, workspace_dir: Path, backend: FsspecSyncBackend
    ) -> None:
        """First checkpoint is a SNAPSHOT with full manifest."""
        f = workspace_dir / "output" / "report.md"
        f.write_text("# Report")
        tracker = manager._dirty_tracker
        tracker.mark_dirty("output/report.md")

        ckpt_id = await manager.create_checkpoint()
        assert ckpt_id == "c001"

        # Verify the stored payload is a SNAPSHOT.
        data = await backend.get_checkpoint("run-123-c001")
        assert data is not None
        from soothe_sdk.protocols.workspace_sync import CheckpointPayload

        payload = CheckpointPayload.model_validate_json(data)
        assert payload.kind == CheckpointType.SNAPSHOT
        assert payload.manifest_snapshot is not None
        assert payload.parent_checkpoint_id is None
        assert len(payload.dirty_files) == 1
        assert payload.dirty_files[0].path == "output/report.md"

    @pytest.mark.asyncio
    async def test_second_checkpoint_is_delta(
        self, manager: CheckpointManager, workspace_dir: Path, backend: FsspecSyncBackend
    ) -> None:
        """Second checkpoint is a DELTA referencing the first."""
        # First checkpoint.
        f1 = workspace_dir / "output" / "a.md"
        f1.write_text("A")
        manager._dirty_tracker.mark_dirty("output/a.md")
        await manager.create_checkpoint()

        # Second checkpoint.
        f2 = workspace_dir / "output" / "b.md"
        f2.write_text("B")
        manager._dirty_tracker.mark_dirty("output/b.md")
        ckpt_id = await manager.create_checkpoint()
        assert ckpt_id == "c002"

        data = await backend.get_checkpoint("run-123-c002")
        assert data is not None
        from soothe_sdk.protocols.workspace_sync import CheckpointPayload

        payload = CheckpointPayload.model_validate_json(data)
        assert payload.kind == CheckpointType.DELTA
        assert payload.manifest_snapshot is None
        assert payload.parent_checkpoint_id == "c001"
        assert len(payload.dirty_files) == 1
        assert payload.dirty_files[0].path == "output/b.md"

    @pytest.mark.asyncio
    async def test_compaction_creates_snapshot(
        self, manager: CheckpointManager, workspace_dir: Path, backend: FsspecSyncBackend
    ) -> None:
        """After max_deltas (3), a compaction SNAPSHOT is written."""
        # Create 4 checkpoints (c001=SNAPSHOT, c002-c004=DELTA, c005=SNAPSHOT).
        for i in range(5):
            f = workspace_dir / "output" / f"file{i}.md"
            f.write_text(f"content{i}")
            manager._dirty_tracker.mark_dirty(f"output/file{i}.md")
            await manager.create_checkpoint()

        # c005 should be a SNAPSHOT (compaction after 3 deltas).
        from soothe_sdk.protocols.workspace_sync import CheckpointPayload

        data = await backend.get_checkpoint("run-123-c005")
        assert data is not None
        payload = CheckpointPayload.model_validate_json(data)
        assert payload.kind == CheckpointType.SNAPSHOT
        assert payload.manifest_snapshot is not None

    @pytest.mark.asyncio
    async def test_dirty_blobs_uploaded(
        self, manager: CheckpointManager, workspace_dir: Path, backend: FsspecSyncBackend
    ) -> None:
        """Dirty file content is uploaded as a blob to the backend."""
        data = b"checkpoint me"
        f = workspace_dir / "output" / "data.bin"
        f.write_bytes(data)
        manager._dirty_tracker.mark_dirty("output/data.bin")

        await manager.create_checkpoint()

        h = _sha256(data)
        assert await backend.head_blob(h) is True

    @pytest.mark.asyncio
    async def test_manifest_version_increments(
        self, manager: CheckpointManager, workspace_dir: Path
    ) -> None:
        """Manifest version increments with each checkpoint."""
        f = workspace_dir / "output" / "a.md"
        f.write_text("A")
        manager._dirty_tracker.mark_dirty("output/a.md")
        await manager.create_checkpoint()
        assert manager.manifest is not None
        assert manager.manifest.version == 1

        f.write_text("AA")
        manager._dirty_tracker.mark_dirty("output/a.md")
        await manager.create_checkpoint()
        assert manager.manifest.version == 2

    @pytest.mark.asyncio
    async def test_deleted_files_removed_from_manifest(
        self, manager: CheckpointManager, workspace_dir: Path, backend: FsspecSyncBackend
    ) -> None:
        """Deleted files are removed from the manifest."""
        f = workspace_dir / "output" / "temp.md"
        f.write_text("temp")
        manager._dirty_tracker.mark_dirty("output/temp.md")
        await manager.create_checkpoint()
        assert manager.manifest is not None
        assert any(e.path == "output/temp.md" for e in manager.manifest.artifacts)

        # Delete the file.
        f.unlink()
        manager._dirty_tracker.mark_dirty("output/temp.md")
        await manager.create_checkpoint()
        assert not any(e.path == "output/temp.md" for e in manager.manifest.artifacts)

    @pytest.mark.asyncio
    async def test_dirty_cleared_after_checkpoint(
        self, manager: CheckpointManager, workspace_dir: Path
    ) -> None:
        """Dirty tracker is cleared after a checkpoint."""
        f = workspace_dir / "output" / "a.md"
        f.write_text("A")
        manager._dirty_tracker.mark_dirty("output/a.md")
        assert len(manager._dirty_tracker.dirty_files) == 1

        await manager.create_checkpoint()
        assert len(manager._dirty_tracker.dirty_files) == 0


# ---------------------------------------------------------------------------
# Recovery
# ---------------------------------------------------------------------------


class TestCheckpointRecovery:
    """Tests for crash recovery via snapshot + delta replay."""

    @pytest.mark.asyncio
    async def test_recover_from_snapshot_and_deltas(
        self, manager: CheckpointManager, workspace_dir: Path, backend: FsspecSyncBackend
    ) -> None:
        """Recovery replays snapshot + deltas to restore state."""
        # Create a snapshot + 2 deltas.
        for i in range(3):
            f = workspace_dir / "output" / f"file{i}.md"
            f.write_text(f"content{i}")
            manager._dirty_tracker.mark_dirty(f"output/file{i}.md")
            await manager.create_checkpoint()

        # Simulate crash: create a new manager (no in-memory state).
        manager2 = CheckpointManager(
            run_id="run-123",
            backend=backend,
            cas=manager._cas,
            dirty_tracker=DirtyTracker(workspace_root=workspace_dir),
            workspace_root=workspace_dir,
        )
        await manager2.initialize()

        # The new manager should have recovered the manifest.
        assert manager2.manifest is not None
        assert manager2.manifest.version == 3
        assert len(manager2.manifest.artifacts) == 3

        # Recover the latest state.
        payload = await manager2.recover()
        assert payload is not None
        assert len(payload.dirty_files) == 3

    @pytest.mark.asyncio
    async def test_recover_empty_returns_none(
        self, manager: CheckpointManager, backend: FsspecSyncBackend
    ) -> None:
        """Recovery with no checkpoints returns None."""
        payload = await manager.recover()
        assert payload is None

    @pytest.mark.asyncio
    async def test_recover_handles_missing_delta(
        self, manager: CheckpointManager, workspace_dir: Path, backend: FsspecSyncBackend
    ) -> None:
        """Recovery stops gracefully when a delta is missing."""
        # Create snapshot + delta.
        for i in range(2):
            f = workspace_dir / "output" / f"file{i}.md"
            f.write_text(f"content{i}")
            manager._dirty_tracker.mark_dirty(f"output/file{i}.md")
            await manager.create_checkpoint()

        # Simulate a corrupted/missing delta by deleting c002.
        # (The backend stores at run-123-c002.)
        await manager._backend._to_thread(
            backend._fs.rm, f"{ROOT}/runs/run-123/checkpoints/run-123-c002.json"
        )

        # Recovery should still work, anchored on the snapshot.
        payload = await manager.recover()
        assert payload is not None
        # Only the snapshot's dirty files are recovered.
        assert len(payload.dirty_files) == 1
