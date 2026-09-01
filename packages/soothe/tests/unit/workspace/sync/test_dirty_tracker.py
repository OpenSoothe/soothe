"""Tests for the dirty file tracker.

Tests verify:
    - File creation, modification, and deletion detection via stat-scan.
    - Symlink escape detection (S2).
    - Dirty set management and clearing.
    - Excluded directories are not watched.
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

import pytest

from soothe.workspace.sync.dirty_tracker import (
    DirtyTracker,
    FileEventKind,
)


@pytest.fixture
def workspace_dir(tmp_path: Path) -> Path:
    """Temporary workspace with input/working/output dirs."""
    d = tmp_path / "workspace"
    for subdir in ("input", "working", "output"):
        (d / subdir).mkdir(parents=True)
    return d


@pytest.fixture
def tracker(workspace_dir: Path) -> DirtyTracker:
    """Fresh dirty tracker."""
    return DirtyTracker(workspace_root=workspace_dir, poll_interval=0.1)


# ---------------------------------------------------------------------------
# Baseline and dirty detection
# ---------------------------------------------------------------------------


class TestDirtyTracker:
    """Tests for dirty file tracking."""

    @pytest.mark.asyncio
    async def test_baseline_scan(self, tracker: DirtyTracker, workspace_dir: Path) -> None:
        """Baseline scan captures existing files."""
        (workspace_dir / "input" / "existing.txt").write_text("hello")
        tracker.start()
        assert len(tracker._baseline) == 1
        assert "input/existing.txt" in tracker._baseline
        # No dirty files yet.
        assert len(tracker.dirty_files) == 0
        await tracker.stop()

    @pytest.mark.asyncio
    async def test_mark_dirty_create(self, tracker: DirtyTracker, workspace_dir: Path) -> None:
        """Manually marking a new file as dirty."""
        tracker.start()
        f = workspace_dir / "output" / "new.txt"
        f.write_text("new content")
        tracker.mark_dirty("output/new.txt")

        dirty = tracker.dirty_files
        assert "output/new.txt" in dirty
        assert dirty["output/new.txt"].kind == FileEventKind.CREATE
        await tracker.stop()

    @pytest.mark.asyncio
    async def test_mark_dirty_modify(self, tracker: DirtyTracker, workspace_dir: Path) -> None:
        """Marking an existing baseline file as modify."""
        f = workspace_dir / "input" / "file.txt"
        f.write_text("original")
        tracker.start()

        f.write_text("modified")
        tracker.mark_dirty("input/file.txt")

        dirty = tracker.dirty_files
        assert "input/file.txt" in dirty
        assert dirty["input/file.txt"].kind == FileEventKind.MODIFY
        await tracker.stop()

    @pytest.mark.asyncio
    async def test_mark_dirty_delete(self, tracker: DirtyTracker, workspace_dir: Path) -> None:
        """Marking a deleted file."""
        f = workspace_dir / "input" / "file.txt"
        f.write_text("content")
        tracker.start()

        f.unlink()
        tracker.mark_dirty("input/file.txt")

        assert "input/file.txt" in tracker.deleted_files
        assert "input/file.txt" not in tracker.dirty_files
        await tracker.stop()

    @pytest.mark.asyncio
    async def test_clear(self, tracker: DirtyTracker, workspace_dir: Path) -> None:
        """Clearing dirty state after a checkpoint."""
        tracker.start()
        (workspace_dir / "output" / "a.txt").write_text("a")
        (workspace_dir / "output" / "b.txt").write_text("b")
        tracker.mark_dirty("output/a.txt")
        tracker.mark_dirty("output/b.txt")

        assert len(tracker.dirty_files) == 2

        tracker.clear()
        assert len(tracker.dirty_files) == 0
        assert len(tracker.deleted_files) == 0
        await tracker.stop()

    @pytest.mark.asyncio
    async def test_excluded_dirs_not_watched(
        self, tracker: DirtyTracker, workspace_dir: Path
    ) -> None:
        """``.workspace/`` directory is excluded from tracking."""
        (workspace_dir / ".workspace").mkdir()
        (workspace_dir / ".workspace" / "state.db").write_text("state")
        tracker.start()

        assert all(".workspace/" not in path for path in tracker._baseline)
        await tracker.stop()

    @pytest.mark.asyncio
    async def test_get_dirty_excludes_rejected_symlinks(
        self, tracker: DirtyTracker, workspace_dir: Path, tmp_path: Path
    ) -> None:
        """S2: rejected symlinks are excluded from get_dirty()."""
        external = tmp_path / "secret.txt"
        external.write_text("secret")
        link = workspace_dir / "input" / "evil.txt"
        os.symlink(external, link)

        tracker.start()
        tracker.mark_dirty("input/evil.txt")

        # The symlink is in dirty_files but with rejected status.
        assert "input/evil.txt" in tracker.dirty_files
        assert tracker.dirty_files["input/evil.txt"].status == "rejected_symlink"

        # get_dirty() excludes it.
        assert "input/evil.txt" not in tracker.get_dirty()

        # get_rejected() returns it.
        assert "input/evil.txt" in tracker.get_rejected()
        await tracker.stop()

    @pytest.mark.asyncio
    async def test_internal_symlink_is_allowed(
        self, tracker: DirtyTracker, workspace_dir: Path
    ) -> None:
        """Symlinks within the workspace are not rejected."""
        target = workspace_dir / "input" / "real.txt"
        target.write_text("real")
        link = workspace_dir / "input" / "link.txt"
        os.symlink(target, link)

        tracker.start()
        tracker.mark_dirty("input/link.txt")

        assert "input/link.txt" in tracker.dirty_files
        assert tracker.dirty_files["input/link.txt"].status == "dirty"
        await tracker.stop()

    @pytest.mark.asyncio
    async def test_stat_scan_detects_changes(self, workspace_dir: Path) -> None:
        """Stat-scan polling detects new files."""
        tracker = DirtyTracker(workspace_root=workspace_dir, poll_interval=0.05)
        tracker.start()
        # Give the poll loop a moment to start.
        await asyncio.sleep(0.1)

        # Create a new file.
        (workspace_dir / "output" / "report.md").write_text("report")
        # Wait for the poll loop to detect it.
        await asyncio.sleep(0.3)

        assert "output/report.md" in tracker.dirty_files

        await tracker.stop()


# ---------------------------------------------------------------------------
# Symlink detection
# ---------------------------------------------------------------------------


class TestSymlinkDetection:
    """S2: symlink escape detection in the dirty tracker."""

    @pytest.mark.asyncio
    async def test_external_symlink_rejected(self, workspace_dir: Path, tmp_path: Path) -> None:
        """Symlink to external file is rejected."""
        external = tmp_path / "passwd"
        external.write_text("root:x:0:0")
        link = workspace_dir / "input" / "evil.txt"
        os.symlink(external, link)

        tracker = DirtyTracker(workspace_root=workspace_dir)
        tracker.start()
        tracker.mark_dirty("input/evil.txt")

        assert tracker.dirty_files["input/evil.txt"].status == "rejected_symlink"
        await tracker.stop()

    @pytest.mark.asyncio
    async def test_nested_external_symlink_rejected(
        self, workspace_dir: Path, tmp_path: Path
    ) -> None:
        """Symlink deep in a subdir pointing outside is rejected."""
        external_dir = tmp_path / "external"
        external_dir.mkdir()
        (external_dir / "secret.txt").write_text("secret")
        (workspace_dir / "working" / "sub").mkdir()
        link = workspace_dir / "working" / "sub" / "evil.txt"
        os.symlink(external_dir / "secret.txt", link)

        tracker = DirtyTracker(workspace_root=workspace_dir)
        tracker.start()
        tracker.mark_dirty("working/sub/evil.txt")

        assert tracker.dirty_files["working/sub/evil.txt"].status == "rejected_symlink"
        await tracker.stop()
