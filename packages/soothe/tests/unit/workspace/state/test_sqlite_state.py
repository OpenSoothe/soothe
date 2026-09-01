"""Tests for the SQLite workspace state store.

Tests verify CRUD for files, blobs, checkpoints, and artifacts.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from soothe.workspace.state.sqlite import SqliteWorkspaceStateStore


@pytest.fixture
async def store(tmp_path: Path) -> SqliteWorkspaceStateStore:
    """Fresh SQLite state store."""
    db_path = tmp_path / "state.db"
    s = SqliteWorkspaceStateStore(db_path=db_path, run_id="run-001")
    yield s
    await s.close()


# ---------------------------------------------------------------------------
# File tracking
# ---------------------------------------------------------------------------


class TestFileTracking:
    """Tests for upsert_file, get_file, list_dirty_files, clear_dirty."""

    async def test_upsert_and_get_file(self, store: SqliteWorkspaceStateStore) -> None:
        await store.upsert_file(
            "output/report.md",
            size=1024,
            mtime=1000.0,
            inode=12345,
            sha256="abc123",
            status="dirty",
        )
        result = await store.get_file("output/report.md")
        assert result is not None
        assert result["path"] == "output/report.md"
        assert result["size"] == 1024
        assert result["sha256"] == "abc123"
        assert result["status"] == "dirty"

    async def test_get_file_missing(self, store: SqliteWorkspaceStateStore) -> None:
        assert await store.get_file("nonexistent.txt") is None

    async def test_list_dirty_files(self, store: SqliteWorkspaceStateStore) -> None:
        await store.upsert_file("a.txt", size=10, mtime=1.0, inode=1, sha256="a", status="dirty")
        await store.upsert_file("b.txt", size=20, mtime=2.0, inode=2, sha256="b", status="clean")
        await store.upsert_file("c.txt", size=30, mtime=3.0, inode=3, sha256="c", status="dirty")

        dirty = await store.list_dirty_files()
        assert len(dirty) == 2
        paths = {d["path"] for d in dirty}
        assert paths == {"a.txt", "c.txt"}

    async def test_clear_dirty(self, store: SqliteWorkspaceStateStore) -> None:
        await store.upsert_file("a.txt", size=10, mtime=1.0, inode=1, sha256="a", status="dirty")
        await store.clear_dirty()
        dirty = await store.list_dirty_files()
        assert len(dirty) == 0

    async def test_upsert_file_updates_existing(self, store: SqliteWorkspaceStateStore) -> None:
        await store.upsert_file("a.txt", size=10, mtime=1.0, inode=1, sha256="a", status="dirty")
        await store.upsert_file("a.txt", size=20, mtime=2.0, inode=1, sha256="b", status="clean")
        result = await store.get_file("a.txt")
        assert result is not None
        assert result["size"] == 20
        assert result["status"] == "clean"


# ---------------------------------------------------------------------------
# Blob cache
# ---------------------------------------------------------------------------


class TestBlobCache:
    """Tests for upsert_blob, get_blob."""

    async def test_upsert_and_get_blob(self, store: SqliteWorkspaceStateStore) -> None:
        await store.upsert_blob(
            "sha256abc",
            size=4096,
            local_path="/cache/blobs/sha256/ab/sha256abc",
            last_used=1000.0,
        )
        result = await store.get_blob("sha256abc")
        assert result is not None
        assert result["sha256"] == "sha256abc"
        assert result["size"] == 4096
        assert result["local_path"] == "/cache/blobs/sha256/ab/sha256abc"

    async def test_get_blob_missing(self, store: SqliteWorkspaceStateStore) -> None:
        assert await store.get_blob("nonexistent") is None


# ---------------------------------------------------------------------------
# Checkpoint references
# ---------------------------------------------------------------------------


class TestCheckpointRefs:
    """Tests for insert_checkpoint, list_pending_checkpoints, update_checkpoint_status."""

    async def test_insert_and_list_pending(self, store: SqliteWorkspaceStateStore) -> None:
        await store.insert_checkpoint("c001", manifest_hash="hash1", status="pending_upload")
        await store.insert_checkpoint("c002", manifest_hash="hash2", status="pending_upload")
        await store.insert_checkpoint("c003", manifest_hash="hash3", status="uploaded")

        pending = await store.list_pending_checkpoints()
        assert len(pending) == 2
        ids = {p["id"] for p in pending}
        assert ids == {"c001", "c002"}

    async def test_update_checkpoint_status(self, store: SqliteWorkspaceStateStore) -> None:
        await store.insert_checkpoint("c001", manifest_hash="hash1", status="pending_upload")
        await store.update_checkpoint_status("c001", "uploaded")

        pending = await store.list_pending_checkpoints()
        assert len(pending) == 0

    async def test_list_pending_empty(self, store: SqliteWorkspaceStateStore) -> None:
        pending = await store.list_pending_checkpoints()
        assert len(pending) == 0


# ---------------------------------------------------------------------------
# Artifact tracking
# ---------------------------------------------------------------------------


class TestArtifactTracking:
    """Tests for upsert_artifact."""

    async def test_upsert_artifact(self, store: SqliteWorkspaceStateStore) -> None:
        await store.upsert_artifact(
            "output/report.md",
            sha256="abc123",
            published_uri="s3://bucket/artifacts/report.md",
            status="published",
        )
        # No get_artifact in protocol — just verify no error.


# ---------------------------------------------------------------------------
# Cleanup
# ---------------------------------------------------------------------------


class TestCleanup:
    """Tests for cleanup."""

    async def test_cleanup_removes_all_data(self, store: SqliteWorkspaceStateStore) -> None:
        await store.upsert_file("a.txt", size=10, mtime=1.0, inode=1, sha256="a", status="dirty")
        await store.upsert_blob("sha", size=10, local_path="/p", last_used=1.0)
        await store.insert_checkpoint("c001", manifest_hash="h", status="pending_upload")

        await store.cleanup()

        assert await store.get_file("a.txt") is None
        assert await store.get_blob("sha") is None
        assert await store.list_pending_checkpoints() == []
