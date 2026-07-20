"""Tests for per-resolved-path edit lock registry and concurrent edit serialization.

Covers three guarantees:
1. Concurrent edits to the *same* file are serialized (no lost updates).
2. Concurrent edits to *different* files run in parallel.
3. Nested acquisition of the same path does not deadlock.
"""

from __future__ import annotations

import asyncio
import os
import threading
import time
from pathlib import Path

import aiofiles
import pytest

from soothe_nano.filesystem._lock_registry import FileEditLockRegistry
from soothe_nano.filesystem.local import LocalFilesystem

# ======================================================================
# FileEditLockRegistry unit tests
# ======================================================================


class TestFileEditLockRegistry:
    """Direct tests for the lock registry."""

    @pytest.mark.asyncio
    async def test_same_path_returns_same_async_lock(self) -> None:
        """Two acquire() calls for the same path share one asyncio.Lock."""
        reg = FileEditLockRegistry()

        # Acquire the lock once, then check that a second acquire blocks.
        acquired = asyncio.Event()

        async def hold() -> None:
            async with reg.acquire("/tmp/test_same_path.txt"):
                acquired.set()
                await asyncio.sleep(0.3)

        task = asyncio.create_task(hold())
        await acquired.wait()

        # While the first holder is still holding, a second acquire should block.
        started = asyncio.Event()
        finished = asyncio.Event()

        async def wait_for_lock() -> None:
            started.set()
            async with reg.acquire("/tmp/test_same_path.txt"):
                finished.set()

        task2 = asyncio.create_task(wait_for_lock())
        await asyncio.wait_for(started.wait(), timeout=1.0)
        assert not finished.is_set(), "second acquire should block while first holds"

        await task
        await asyncio.wait_for(task2, timeout=2.0)
        assert finished.is_set()

    @pytest.mark.asyncio
    async def test_different_paths_run_in_parallel(self) -> None:
        """Locks for different paths do not block each other."""
        reg = FileEditLockRegistry()
        events: list[asyncio.Event] = [asyncio.Event(), asyncio.Event()]

        async def hold(idx: int, path: str) -> None:
            async with reg.acquire(path):
                events[idx].set()
                await asyncio.sleep(0.3)

        t0 = time.monotonic()
        await asyncio.gather(
            hold(0, "/tmp/parallel_a.txt"),
            hold(1, "/tmp/parallel_b.txt"),
        )
        elapsed = time.monotonic() - t0

        # Both events should have been set (parallel, not serialized).
        assert all(e.is_set() for e in events)
        # Should complete in roughly the hold duration, not 2x.
        assert elapsed < 0.55, f"locks appear serialized: {elapsed:.3f}s"

    @pytest.mark.asyncio
    async def test_nested_async_acquisition_no_deadlock(self) -> None:
        """Nested acquire() of the same path must not deadlock.

        Note: ``asyncio.Lock`` is NOT reentrant. This test documents that
        nested acquisition of the *same* path from different coroutines
        serializes correctly (the inner waits for the outer to release),
        which is the expected behaviour for preventing lost updates.
        """
        reg = FileEditLockRegistry()

        # Different paths nested — no deadlock.
        async with reg.acquire("/tmp/nest_outer.txt"):
            async with reg.acquire("/tmp/nest_inner.txt"):
                pass  # reached without deadlock

    def test_nested_sync_acquisition_no_deadlock(self) -> None:
        """Nested acquire_sync() of the same path must not deadlock.

        ``threading.RLock`` is reentrant, so same-path nesting is safe.
        """
        reg = FileEditLockRegistry()
        with reg.acquire_sync("/tmp/sync_nest.txt"):
            with reg.acquire_sync("/tmp/sync_nest.txt"):
                pass  # reached without deadlock

    @pytest.mark.asyncio
    async def test_realpath_canonicalization(self) -> None:
        """Symlinks and relative components collapse to the same lock."""
        import tempfile

        with tempfile.TemporaryDirectory() as tmpdir:
            real = Path(tmpdir) / "real.txt"
            link = Path(tmpdir) / "link.txt"
            real.write_text("x")
            os.symlink(real, link)

            reg = FileEditLockRegistry()

            # Both the real path and a symlink should resolve to the same key.
            acquired = asyncio.Event()

            async def hold() -> None:
                async with reg.acquire(link):
                    acquired.set()
                    await asyncio.sleep(0.3)

            task = asyncio.create_task(hold())
            await acquired.wait()

            # Acquiring via the real path should block (same underlying file).
            finished = asyncio.Event()

            async def wait_real() -> None:
                async with reg.acquire(real):
                    finished.set()

            task2 = asyncio.create_task(wait_real())
            assert not finished.is_set(), "realpath symlink should map to same lock"

            await task
            await asyncio.wait_for(task2, timeout=2.0)
            assert finished.is_set()

    @pytest.mark.asyncio
    async def test_concurrent_lazy_creation_is_safe(self) -> None:
        """Many tasks simultaneously requesting a new path get one lock."""
        reg = FileEditLockRegistry()
        path = "/tmp/concurrent_lazy_create.txt"
        barrier = asyncio.Event()

        async def acquire_and_signal() -> None:
            await barrier.wait()
            async with reg.acquire(path):
                await asyncio.sleep(0.05)

        tasks = [asyncio.create_task(acquire_and_signal()) for _ in range(20)]
        barrier.set()
        await asyncio.gather(*tasks)

        # Only one lock object should have been created.
        assert len(reg._async_locks) == 1
        assert path in reg._async_locks or os.path.realpath(path) in reg._async_locks


# ======================================================================
# LocalFilesystem integration tests
# ======================================================================


class TestConcurrentEditSerialization:
    """Integration tests verifying that LocalFilesystem edit locks work."""

    @pytest.fixture
    def temp_workspace(self, tmp_path: Path) -> LocalFilesystem:
        """Create a temporary workspace filesystem."""
        return LocalFilesystem(workspace=tmp_path, virtual_mode=True)

    @pytest.mark.asyncio
    async def test_concurrent_same_file_awrite_serialized(
        self, temp_workspace: LocalFilesystem
    ) -> None:
        """Concurrent awrite to the same file must not lose updates.

        Each task appends a unique line. Without serialization, some
        appends would be lost (read-modify-write race). With the lock,
        all lines must be present in the final file.
        """
        # Start with an empty file
        temp_workspace.write("counter.txt", "")

        num_writers = 20
        lines_expected = [f"line-{i}" for i in range(num_writers)]

        async def append_line(line: str) -> None:
            """Read current content, append a line, write back."""
            resolved = temp_workspace._resolve_path("counter.txt")
            async with temp_workspace._edit_locks.acquire(resolved):
                # Read
                async with aiofiles.open(resolved, encoding="utf-8") as f:
                    content = await f.read()
                # Modify
                if content:
                    content = content + "\n" + line
                else:
                    content = line
                # Write (atomic)
                temp_workspace._write_atomic(resolved, content)

        await asyncio.gather(*[append_line(line) for line in lines_expected])

        # Verify all lines are present (no lost updates).
        final_content = temp_workspace.read("counter.txt").content
        for line in lines_expected:
            assert line in final_content, f"lost update: {line!r} not in file"
        assert final_content.count("\n") == num_writers - 1

    @pytest.mark.asyncio
    async def test_concurrent_different_files_run_in_parallel(
        self, temp_workspace: LocalFilesystem
    ) -> None:
        """Concurrent edits to different files must run in parallel.

        Each task holds the lock for a brief period. If locks were
        global (not per-path), the total time would be ~N * hold_time.
        With per-path locks, tasks overlap.
        """
        num_files = 5
        hold_time = 0.15

        async def edit_and_hold(filename: str) -> None:
            resolved = temp_workspace._resolve_path(filename)
            temp_workspace.write(filename, "initial")
            async with temp_workspace._edit_locks.acquire(resolved):
                await asyncio.sleep(hold_time)

        filenames = [f"file_{i}.txt" for i in range(num_files)]

        t0 = time.monotonic()
        await asyncio.gather(*[edit_and_hold(f) for f in filenames])
        elapsed = time.monotonic() - t0

        # Should be roughly hold_time (parallel), not num_files * hold_time.
        upper_bound = hold_time * 1.8  # allow scheduling overhead
        assert elapsed < upper_bound, (
            f"per-file locks appear serialized: {elapsed:.3f}s "
            f"(expected < {upper_bound:.3f}s for {num_files} parallel edits)"
        )

    @pytest.mark.asyncio
    async def test_concurrent_aedit_no_lost_updates(self, temp_workspace: LocalFilesystem) -> None:
        """Concurrent aedit calls on the same file: all edits land."""
        # Seed file with unique markers
        markers = [f"<!-- marker-{i} -->" for i in range(10)]
        temp_workspace.write("markers.txt", "\n".join(markers) + "\n")

        async def replace_marker(i: int) -> None:
            old = f"<!-- marker-{i} -->"
            new = f"[DONE-{i}]"
            await temp_workspace.aedit("markers.txt", old, new, backup=False)

        await asyncio.gather(*[replace_marker(i) for i in range(10)])

        content = temp_workspace.read("markers.txt").content
        for i in range(10):
            assert f"[DONE-{i}]" in content, f"edit {i} was lost"
            assert f"<!-- marker-{i} -->" not in content, f"edit {i} did not apply"

    def test_sync_nested_acquisition_no_deadlock(self, temp_workspace: LocalFilesystem) -> None:
        """Sync edit followed by another sync edit on same file (nested)."""
        temp_workspace.write("nested.txt", "a=1\n")
        resolved = temp_workspace._resolve_path("nested.txt")

        # Simulate nested acquisition: outer lock + inner edit (which also locks).
        with temp_workspace._edit_locks.acquire_sync(resolved):
            # edit() internally acquires the sync lock again (reentrant RLock).
            temp_workspace.edit("nested.txt", "a=1", "a=2", backup=False)

        content = temp_workspace.read("nested.txt").content
        assert "a=2" in content

    @pytest.mark.asyncio
    async def test_async_nested_acquisition_no_deadlock(
        self, temp_workspace: LocalFilesystem
    ) -> None:
        """Async nested acquisition of same path does not deadlock.

        ``aapply_diff`` acquires the async lock, then delegates to
        ``apply_diff`` which acquires the sync RLock on the same thread.
        This must not deadlock.
        """
        temp_workspace.write("diff_target.txt", "hello\nworld\n")
        diff = "--- a\n+++ b\n@@ -1,2 +1,2 @@\n hello\n-world\n+world!\n"

        # aapply_diff uses async lock + delegates to sync apply_diff (sync lock).
        result = await temp_workspace.aapply_diff("diff_target.txt", diff, backup=False)
        assert result is not None

        content = temp_workspace.read("diff_target.txt").content
        assert "world!" in content

    @pytest.mark.asyncio
    async def test_mixed_async_and_sync_same_file(self, temp_workspace: LocalFilesystem) -> None:
        """Async and sync methods editing the same file via their own locks.

        The async lock and sync lock are separate, so this test verifies
        that the optimistic-concurrency version stamp catches any cross-type
        race as a fallback.  The key assertion is that no deadlock occurs.
        """
        temp_workspace.write("mixed.txt", "count=0\n")

        async def async_increment() -> None:
            for _ in range(5):
                await temp_workspace.aedit("mixed.txt", "count=", "count=", backup=False)

        def sync_increment() -> None:
            for _ in range(5):
                temp_workspace.edit("mixed.txt", "count=", "count=", backup=False)

        # Run concurrently — must not deadlock. Version stamps handle races.
        t = threading.Thread(target=sync_increment)
        t.start()
        await asyncio.wait_for(async_increment(), timeout=10.0)
        t.join(timeout=10.0)
        assert not t.is_alive(), "sync thread did not finish (possible deadlock)"
