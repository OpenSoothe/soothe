"""Tests for the ``FsspecSyncBackend`` using ``MemoryFileSystem``.

These tests verify the backend's correctness without requiring an actual
S3/MinIO/GCS endpoint.  ``MemoryFileSystem`` provides a zero-I/O in-process
filesystem that implements the full fsspec ``AbstractFileSystem`` interface.
"""

from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING

import pytest
from fsspec.implementations.memory import MemoryFileSystem

from soothe.workspace.sync.backends.fsspec import FsspecSyncBackend
from soothe.workspace.sync.errors import (
    ConcurrentModificationError,
    IntegrityError,
)

if TYPE_CHECKING:
    pass

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

ROOT = "/test-workspace-sync"


@pytest.fixture
def fs() -> MemoryFileSystem:
    """Fresh in-memory filesystem for each test."""
    mem = MemoryFileSystem()
    yield mem
    # Clean up after each test
    try:
        mem.rm(ROOT, recursive=True)
    except FileNotFoundError:
        pass
    mem.store.clear()


@pytest.fixture
def backend(fs: MemoryFileSystem) -> FsspecSyncBackend:
    """Fresh backend instance for each test."""
    b = FsspecSyncBackend(fs=fs, root=ROOT, max_workers=2)
    yield b
    b.close()


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


# ---------------------------------------------------------------------------
# Blob operations
# ---------------------------------------------------------------------------


class TestBlobOps:
    """Tests for get_blob, put_blob, head_blob."""

    async def test_put_and_get_blob(self, backend: FsspecSyncBackend) -> None:
        data = b"hello world"
        h = _sha256(data)
        await backend.put_blob(h, data)

        assert await backend.head_blob(h) is True
        result = await backend.get_blob(h)
        assert result == data

    async def test_get_blob_missing(self, backend: FsspecSyncBackend) -> None:
        h = _sha256(b"nonexistent")
        assert await backend.get_blob(h) is None
        assert await backend.head_blob(h) is False

    async def test_put_blob_idempotent(self, backend: FsspecSyncBackend) -> None:
        data = b"test content"
        h = _sha256(data)

        await backend.put_blob(h, data)
        await backend.put_blob(h, data)  # second call is no-op

        result = await backend.get_blob(h)
        assert result == data

    async def test_put_blob_integrity_mismatch(self, backend: FsspecSyncBackend) -> None:
        """S7: put_blob rejects data whose hash doesn't match."""
        real_hash = _sha256(b"real data")
        wrong_data = b"wrong data"

        with pytest.raises(IntegrityError, match="hash mismatch"):
            await backend.put_blob(real_hash, wrong_data)

        # Blob should not have been stored
        assert await backend.head_blob(real_hash) is False


# ---------------------------------------------------------------------------
# Manifest operations
# ---------------------------------------------------------------------------


class TestManifestOps:
    """Tests for get_manifest, put_manifest (optimistic concurrency)."""

    async def test_put_and_get_manifest(
        self,
        backend: FsspecSyncBackend,
    ) -> None:
        from soothe_sdk.protocols.workspace_sync import Manifest, ManifestEntry

        manifest = Manifest(
            run_id="run-001",
            version=1,
            resources=[ManifestEntry(path="input/paper.pdf", sha256="abc123", size=100)],
            artifacts=[],
        )

        await backend.put_manifest("run-001", manifest)

        result = await backend.get_manifest("run-001")
        assert result is not None
        assert result.run_id == "run-001"
        assert result.version == 1
        assert len(result.resources) == 1
        assert result.resources[0].path == "input/paper.pdf"

    async def test_get_manifest_missing(self, backend: FsspecSyncBackend) -> None:
        result = await backend.get_manifest("nonexistent-run")
        assert result is None

    async def test_put_manifest_optimistic_concurrency_success(
        self,
        backend: FsspecSyncBackend,
    ) -> None:
        from soothe_sdk.protocols.workspace_sync import Manifest

        # Write version 1
        m1 = Manifest(run_id="run-002", version=1)
        await backend.put_manifest("run-002", m1)

        # Update to version 2 with if_match=1
        m2 = Manifest(run_id="run-002", version=2)
        result = await backend.put_manifest("run-002", m2, if_match="1")
        assert result.version == 2

    async def test_put_manifest_optimistic_concurrency_conflict(
        self,
        backend: FsspecSyncBackend,
    ) -> None:
        from soothe_sdk.protocols.workspace_sync import Manifest

        # Write version 1
        m1 = Manifest(run_id="run-003", version=1)
        await backend.put_manifest("run-003", m1)

        # Try to write version 2 with stale if_match=5
        m2 = Manifest(run_id="run-003", version=2)
        with pytest.raises(ConcurrentModificationError, match="version mismatch"):
            await backend.put_manifest("run-003", m2, if_match="5")


# ---------------------------------------------------------------------------
# Checkpoint operations
# ---------------------------------------------------------------------------


class TestCheckpointOps:
    """Tests for list_checkpoints, get_checkpoint, put_checkpoint."""

    async def test_put_and_get_checkpoint(
        self,
        backend: FsspecSyncBackend,
    ) -> None:
        data = b'{"checkpoint_id": "run-004-c001", "kind": "snapshot"}'
        await backend.put_checkpoint("run-004-c001", data)

        result = await backend.get_checkpoint("run-004-c001")
        assert result == data

    async def test_get_checkpoint_missing(self, backend: FsspecSyncBackend) -> None:
        result = await backend.get_checkpoint("run-999-c999")
        assert result is None

    async def test_list_checkpoints(
        self,
        backend: FsspecSyncBackend,
    ) -> None:
        c1 = b'{"checkpoint_id": "run-005-c001", "kind": "snapshot"}'
        c2 = b'{"checkpoint_id": "run-005-c002", "kind": "delta"}'
        c3 = b'{"checkpoint_id": "run-005-c003", "kind": "delta"}'

        await backend.put_checkpoint("run-005-c001", c1)
        await backend.put_checkpoint("run-005-c002", c2)
        await backend.put_checkpoint("run-005-c003", c3)

        ids = await backend.list_checkpoints("run-005")
        assert len(ids) == 3
        assert "run-005-c001" in ids
        assert "run-005-c002" in ids
        assert "run-005-c003" in ids

    async def test_list_checkpoints_empty(self, backend: FsspecSyncBackend) -> None:
        ids = await backend.list_checkpoints("run-empty")
        assert ids == []


# ---------------------------------------------------------------------------
# Publish operations
# ---------------------------------------------------------------------------


class TestPublishOps:
    """Tests for publish_artifact."""

    async def test_publish_artifact(
        self,
        backend: FsspecSyncBackend,
    ) -> None:
        data = b"# Report\n\nThis is a test report."
        artifact = await backend.publish_artifact("output/report.md", data)

        assert artifact.path == "output/report.md"
        assert artifact.sha256 == _sha256(data)
        assert artifact.size == len(data)
        assert artifact.published_uri is not None
        assert "report.md" in artifact.published_uri


# ---------------------------------------------------------------------------
# Streaming
# ---------------------------------------------------------------------------


class TestStreaming:
    """Tests for stream_blob, stream_checkpoint."""

    async def test_stream_blob(
        self,
        backend: FsspecSyncBackend,
    ) -> None:
        data = b"x" * 200_000  # larger than chunk size
        h = _sha256(data)
        await backend.put_blob(h, data)

        chunks: list[bytes] = []
        async for chunk in backend.stream_blob(h):
            chunks.append(chunk)

        assert b"".join(chunks) == data

    async def test_stream_blob_missing(
        self,
        backend: FsspecSyncBackend,
    ) -> None:
        h = _sha256(b"missing")
        chunks: list[bytes] = []
        async for chunk in backend.stream_blob(h):
            chunks.append(chunk)
        assert chunks == []


# ---------------------------------------------------------------------------
# Security: path traversal prevention (S1)
# ---------------------------------------------------------------------------


class TestPathTraversalSecurity:
    """S1: path traversal protection in backend path construction."""

    async def test_put_blob_rejects_traversal_hash(self, backend: FsspecSyncBackend) -> None:
        """sha256 with path separators is rejected."""
        with pytest.raises(ValueError, match="invalid sha256"):
            await backend.put_blob("../../etc/passwd", b"data")

    async def test_get_blob_rejects_traversal_hash(self, backend: FsspecSyncBackend) -> None:
        with pytest.raises(ValueError, match="invalid sha256"):
            await backend.get_blob("../escape")

    async def test_publish_artifact_rejects_traversal(self, backend: FsspecSyncBackend) -> None:
        """artifact_path with .. is rejected."""
        with pytest.raises(ValueError, match="path traversal|invalid"):
            await backend.publish_artifact("../../etc/passwd", b"data")

    async def test_publish_artifact_rejects_absolute(self, backend: FsspecSyncBackend) -> None:
        with pytest.raises(ValueError, match="absolute"):
            await backend.publish_artifact("/etc/passwd", b"data")

    async def test_publish_artifact_rejects_null_bytes(self, backend: FsspecSyncBackend) -> None:
        with pytest.raises(ValueError, match="null"):
            await backend.publish_artifact("output\x00evil.txt", b"data")

    async def test_manifest_path_rejects_traversal(
        self,
        backend: FsspecSyncBackend,
    ) -> None:
        from soothe_sdk.protocols.workspace_sync import Manifest

        m = Manifest(run_id="../escape", version=1)
        with pytest.raises(ValueError, match="invalid run_id"):
            await backend.put_manifest("../escape", m)

    async def test_checkpoint_path_rejects_traversal(
        self,
        backend: FsspecSyncBackend,
    ) -> None:
        with pytest.raises(ValueError, match="invalid checkpoint_id"):
            await backend.put_checkpoint("../escape-c001", b"data")
