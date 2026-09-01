"""Tests for the background uploader (§32, P10).

Tests verify:
    - Pending checkpoints are uploaded FIFO.
    - Status is updated to 'uploaded' after successful push.
    - Backpressure callback fires when pending count exceeds max_pending.
    - Stop drains the queue before shutting down.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from soothe.workspace.sync.uploader import (
    BackgroundUploader,
)


class FakeStore:
    """In-memory pending checkpoint store for testing."""

    def __init__(self) -> None:
        self._pending: list[dict[str, Any]] = []
        self._statuses: dict[str, str] = {}

    async def list_pending_checkpoints(self) -> list[dict[str, Any]]:
        return list(self._pending)

    async def update_checkpoint_status(self, checkpoint_id: str, status: str) -> None:
        self._statuses[checkpoint_id] = status
        self._pending = [p for p in self._pending if p["checkpoint_id"] != checkpoint_id]

    def add_pending(self, checkpoint_id: str, data: bytes = b"{}") -> None:
        self._pending.append({"checkpoint_id": checkpoint_id, "data": data, "manifest": None})

    @property
    def statuses(self) -> dict[str, str]:
        return self._statuses


class FakeBackend:
    """Fake backend that records put_checkpoint calls."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, bytes]] = []

    async def put_checkpoint(self, checkpoint_id: str, data: bytes, manifest: Any = None) -> None:
        self.calls.append((checkpoint_id, data))


@pytest.fixture
def store() -> FakeStore:
    return FakeStore()


@pytest.fixture
def backend() -> FakeBackend:
    return FakeBackend()


@pytest.fixture
def uploader(backend: FakeBackend, store: FakeStore) -> BackgroundUploader:
    return BackgroundUploader(
        backend=backend,
        store=store,
        max_pending=3,
        poll_interval=0.05,
    )


# ---------------------------------------------------------------------------
# Upload tests
# ---------------------------------------------------------------------------


class TestBackgroundUploader:
    """Tests for the background uploader."""

    @pytest.mark.asyncio
    async def test_uploads_pending_checkpoints(
        self, uploader: BackgroundUploader, store: FakeStore, backend: FakeBackend
    ) -> None:
        """Pending checkpoints are uploaded FIFO."""
        store.add_pending("c001", b"payload1")
        store.add_pending("c002", b"payload2")

        uploader.start()
        await asyncio.sleep(0.3)
        await uploader.stop()

        assert len(backend.calls) == 2
        assert backend.calls[0] == ("c001", b"payload1")
        assert backend.calls[1] == ("c002", b"payload2")
        assert store.statuses["c001"] == "uploaded"
        assert store.statuses["c002"] == "uploaded"

    @pytest.mark.asyncio
    async def test_backpressure_callback(self, backend: FakeBackend, store: FakeStore) -> None:
        """P10: backpressure callback fires when pending > max_pending."""
        calls: list[int] = []
        uploader = BackgroundUploader(
            backend=backend,
            store=store,
            max_pending=2,
            poll_interval=0.05,
            on_backpressure=lambda count: calls.append(count),
        )
        store.add_pending("c001")
        store.add_pending("c002")
        store.add_pending("c003")

        uploader.start()
        await asyncio.sleep(0.3)
        await uploader.stop()

        assert len(calls) > 0
        assert calls[0] >= 3

    @pytest.mark.asyncio
    async def test_stop_drains_queue(
        self, uploader: BackgroundUploader, store: FakeStore, backend: FakeBackend
    ) -> None:
        """Stop drains remaining pending checkpoints before shutting down."""
        store.add_pending("c001")
        store.add_pending("c002")
        store.add_pending("c003")

        uploader.start()
        await asyncio.sleep(0.1)  # Let it start
        await uploader.stop()

        assert len(backend.calls) == 3
        assert len(store._pending) == 0

    @pytest.mark.asyncio
    async def test_no_pending_no_uploads(
        self, uploader: BackgroundUploader, backend: FakeBackend
    ) -> None:
        """No pending checkpoints means no uploads."""
        uploader.start()
        await asyncio.sleep(0.2)
        await uploader.stop()

        assert len(backend.calls) == 0

    @pytest.mark.asyncio
    async def test_failed_upload_keeps_pending(self, store: FakeStore) -> None:
        """A failed upload leaves the checkpoint pending for retry."""

        class FailingBackend:
            async def put_checkpoint(
                self, checkpoint_id: str, data: bytes, manifest: Any = None
            ) -> None:
                raise RuntimeError("network error")

        uploader = BackgroundUploader(
            backend=FailingBackend(),
            store=store,
            max_pending=10,
            poll_interval=0.05,
        )
        store.add_pending("c001")

        uploader.start()
        await asyncio.sleep(0.3)
        await uploader.stop()

        # Checkpoint should still be pending.
        assert len(store._pending) == 1
        assert store._pending[0]["checkpoint_id"] == "c001"
