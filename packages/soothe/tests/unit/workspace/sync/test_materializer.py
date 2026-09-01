"""Tests for the incremental materializer.

Uses ``MemoryFileSystem`` + ``FsspecSyncBackend`` as the remote backend
and a temporary directory as the local workspace + CAS cache.
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path

import pytest
from fsspec.implementations.memory import MemoryFileSystem
from soothe_sdk.protocols.workspace_sync import (
    Manifest,
    ManifestEntry,
)

from soothe.workspace.sync.backends.fsspec import FsspecSyncBackend
from soothe.workspace.sync.cas import CASCache
from soothe.workspace.sync.materializer import Materializer

ROOT = "/test-materializer"


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


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
    b = FsspecSyncBackend(fs=fs, root=ROOT, max_workers=2)
    yield b
    b.close()


@pytest.fixture
def cache_dir(tmp_path: Path) -> Path:
    d = tmp_path / "agent-cache"
    d.mkdir()
    return d


@pytest.fixture
def cas(cache_dir: Path) -> CASCache:
    return CASCache(cache_dir)


@pytest.fixture
def workspace_dir(tmp_path: Path) -> Path:
    d = tmp_path / "workspace"
    (d / "input").mkdir(parents=True)
    return d


@pytest.fixture
def materializer(
    backend: FsspecSyncBackend,
    cas: CASCache,
    workspace_dir: Path,
) -> Materializer:
    return Materializer(
        backend=backend,
        cas=cas,
        workspace_root=workspace_dir,
    )


# ---------------------------------------------------------------------------
# Materialization tests
# ---------------------------------------------------------------------------


class TestMaterialize:
    """Tests for the materialize() method."""

    async def test_materialize_downloads_missing_resource(
        self,
        materializer: Materializer,
        backend: FsspecSyncBackend,
        workspace_dir: Path,
    ) -> None:
        """Resource not in CAS → download from backend → materialize."""
        data = b"paper content"
        h = _sha256(data)
        await backend.put_blob(h, data)

        manifest = Manifest(
            run_id="run-1",
            version=1,
            resources=[ManifestEntry(path="paper.pdf", sha256=h, size=len(data))],
        )

        result = await materializer.materialize(manifest)

        assert result == ["paper.pdf"]
        dest = workspace_dir / "input" / "paper.pdf"
        assert dest.is_file()
        assert dest.read_bytes() == data

    async def test_materialize_uses_cas_cache_hit(
        self,
        materializer: Materializer,
        backend: FsspecSyncBackend,
        cas: CASCache,
        workspace_dir: Path,
    ) -> None:
        """Resource already in CAS → no backend download."""
        data = b"cached content"
        h = _sha256(data)

        # Pre-populate CAS cache.
        cas.store_blob(h, data)

        manifest = Manifest(
            run_id="run-1",
            version=1,
            resources=[ManifestEntry(path="file.txt", sha256=h, size=len(data))],
        )

        result = await materializer.materialize(manifest)

        assert result == ["file.txt"]
        dest = workspace_dir / "input" / "file.txt"
        assert dest.is_file()
        assert dest.read_bytes() == data

    async def test_materialize_skips_already_correct_file(
        self,
        materializer: Materializer,
        backend: FsspecSyncBackend,
        workspace_dir: Path,
    ) -> None:
        """Workspace file already has correct hash → skip."""
        data = b"already here"
        h = _sha256(data)

        # Pre-place the file in the workspace.
        dest = workspace_dir / "input" / "existing.txt"
        dest.write_bytes(data)

        manifest = Manifest(
            run_id="run-1",
            version=1,
            resources=[ManifestEntry(path="existing.txt", sha256=h, size=len(data))],
        )

        result = await materializer.materialize(manifest)

        assert result == []  # nothing materialized — file was already correct
        assert dest.read_bytes() == data

    async def test_materialize_multiple_resources(
        self,
        materializer: Materializer,
        backend: FsspecSyncBackend,
        workspace_dir: Path,
    ) -> None:
        """Materialize multiple resources concurrently."""
        data1 = b"file 1"
        data2 = b"file 2"
        h1 = _sha256(data1)
        h2 = _sha256(data2)
        await backend.put_blob(h1, data1)
        await backend.put_blob(h2, data2)

        manifest = Manifest(
            run_id="run-1",
            version=1,
            resources=[
                ManifestEntry(path="a/file1.txt", sha256=h1, size=len(data1)),
                ManifestEntry(path="b/file2.txt", sha256=h2, size=len(data2)),
            ],
        )

        result = await materializer.materialize(manifest)

        assert set(result) == {"a/file1.txt", "b/file2.txt"}
        assert (workspace_dir / "input" / "a" / "file1.txt").read_bytes() == data1
        assert (workspace_dir / "input" / "b" / "file2.txt").read_bytes() == data2

    async def test_materialize_missing_resource_raises(
        self,
        materializer: Materializer,
        backend: FsspecSyncBackend,
    ) -> None:
        """Resource not in backend → FileNotFoundError."""
        h = _sha256(b"nonexistent")

        manifest = Manifest(
            run_id="run-1",
            version=1,
            resources=[ManifestEntry(path="missing.txt", sha256=h, size=0)],
        )

        with pytest.raises(FileNotFoundError, match="not found in backend"):
            await materializer.materialize(manifest)

    async def test_materialize_removes_escaping_symlink(
        self,
        materializer: Materializer,
        backend: FsspecSyncBackend,
        workspace_dir: Path,
        tmp_path: Path,
    ) -> None:
        """S2: escaping symlinks are removed before materialization."""
        data = b"safe content"
        h = _sha256(data)
        await backend.put_blob(h, data)

        # Create an escaping symlink at the destination.
        external = tmp_path / "secret.txt"
        external.write_text("secret")
        dest = workspace_dir / "input" / "file.txt"
        os.symlink(external, dest)

        manifest = Manifest(
            run_id="run-1",
            version=1,
            resources=[ManifestEntry(path="file.txt", sha256=h, size=len(data))],
        )

        result = await materializer.materialize(manifest)

        assert result == ["file.txt"]
        assert not dest.is_symlink()
        assert dest.read_bytes() == data

    async def test_materialize_replaces_wrong_content(
        self,
        materializer: Materializer,
        backend: FsspecSyncBackend,
        workspace_dir: Path,
    ) -> None:
        """Workspace file has wrong hash → re-materialize."""
        wrong_data = b"wrong content"
        correct_data = b"correct content"
        h = _sha256(correct_data)
        await backend.put_blob(h, correct_data)

        dest = workspace_dir / "input" / "file.txt"
        dest.write_bytes(wrong_data)

        manifest = Manifest(
            run_id="run-1",
            version=1,
            resources=[ManifestEntry(path="file.txt", sha256=h, size=len(correct_data))],
        )

        result = await materializer.materialize(manifest)

        assert result == ["file.txt"]
        assert dest.read_bytes() == correct_data
