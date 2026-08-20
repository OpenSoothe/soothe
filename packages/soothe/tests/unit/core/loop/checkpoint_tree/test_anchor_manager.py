"""Tests for CheckpointAnchorManager."""

from __future__ import annotations

import pytest

from soothe.sloop.checkpoints.anchor_manager import CheckpointAnchorManager


@pytest.mark.asyncio
async def test_capture_iteration_end_anchor_skips_when_checkpointer_none() -> None:
    manager = CheckpointAnchorManager("loop-test")
    await manager.capture_iteration_end_anchor(
        iteration=1,
        thread_id="thread-1",
        checkpointer=None,
        execution_summary={"status": "success"},
    )
