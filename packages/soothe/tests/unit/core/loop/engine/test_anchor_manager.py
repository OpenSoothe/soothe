"""Tests for CheckpointAnchorManager."""

from __future__ import annotations

import pytest
from soothe.foundation.sloop.engine.anchor_manager import CheckpointAnchorManager


@pytest.mark.asyncio
async def test_capture_iteration_start_anchor_skips_when_checkpointer_none() -> None:
    manager = CheckpointAnchorManager("loop-test")
    await manager.capture_iteration_start_anchor(
        iteration=0,
        thread_id="thread-1",
        checkpointer=None,
    )


@pytest.mark.asyncio
async def test_capture_iteration_end_anchor_skips_when_checkpointer_none() -> None:
    manager = CheckpointAnchorManager("loop-test")
    await manager.capture_iteration_end_anchor(
        iteration=1,
        thread_id="thread-1",
        checkpointer=None,
        execution_summary={"status": "success"},
    )
