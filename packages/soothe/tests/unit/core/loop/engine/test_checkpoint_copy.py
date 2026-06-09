"""Tests for ``copy_thread_via_public_api`` (RFC-223).

The helper supplies ``acopy_thread`` semantics on top of any LangGraph
``BaseCheckpointSaver`` via the public ``alist`` + ``aput`` surface.
"""

from __future__ import annotations

import pytest
from langgraph.checkpoint.base import Checkpoint, CheckpointMetadata
from langgraph.checkpoint.memory import InMemorySaver

from soothe.foundation.loop.engine.checkpoint_copy import copy_thread_via_public_api


def _make_checkpoint(checkpoint_id: str) -> Checkpoint:
    """Build a minimal in-memory Checkpoint object for tests."""
    return Checkpoint(
        v=4,
        id=checkpoint_id,
        ts="2026-05-28T00:00:00Z",
        channel_versions={},
        versions_seen={},
        channel_values={},
        updated_channels=[],
    )


@pytest.mark.asyncio
async def test_copy_empty_thread_returns_zero() -> None:
    """When source thread has no checkpoints, copy is a no-op."""
    saver = InMemorySaver()
    count = await copy_thread_via_public_api(saver, "src", "tgt")
    assert count == 0


@pytest.mark.asyncio
async def test_copy_same_source_target_is_noop() -> None:
    saver = InMemorySaver()
    cp = _make_checkpoint("c1")
    cfg = {"configurable": {"thread_id": "same", "checkpoint_ns": ""}}
    await saver.aput(cfg, cp, CheckpointMetadata(), {})

    count = await copy_thread_via_public_api(saver, "same", "same")
    assert count == 0


@pytest.mark.asyncio
async def test_copy_one_checkpoint_appears_under_target() -> None:
    saver = InMemorySaver()

    src_cfg = {"configurable": {"thread_id": "src", "checkpoint_ns": ""}}
    cp = _make_checkpoint("c1")
    await saver.aput(src_cfg, cp, CheckpointMetadata(), {})

    count = await copy_thread_via_public_api(saver, "src", "tgt")
    assert count == 1

    # Target thread now lists the same checkpoint.
    tgt_cfg = {"configurable": {"thread_id": "tgt", "checkpoint_ns": ""}}
    tuples = [t async for t in saver.alist(tgt_cfg)]
    assert len(tuples) == 1
    assert tuples[0].checkpoint["id"] == "c1"
    # Source thread untouched.
    src_tuples = [t async for t in saver.alist(src_cfg)]
    assert len(src_tuples) == 1


@pytest.mark.asyncio
async def test_copy_multiple_checkpoints_preserves_order() -> None:
    saver = InMemorySaver()
    src_cfg = {"configurable": {"thread_id": "src", "checkpoint_ns": ""}}

    # Put three checkpoints in chronological order.
    for i in range(3):
        await saver.aput(src_cfg, _make_checkpoint(f"c{i}"), CheckpointMetadata(), {})

    count = await copy_thread_via_public_api(saver, "src", "tgt")
    assert count == 3

    # alist yields most-recent-first; both threads should match in shape.
    src_ids = [t.checkpoint["id"] async for t in saver.alist(src_cfg)]
    tgt_ids = [
        t.checkpoint["id"]
        async for t in saver.alist({"configurable": {"thread_id": "tgt", "checkpoint_ns": ""}})
    ]
    assert src_ids == tgt_ids
    assert len(src_ids) == 3


@pytest.mark.asyncio
async def test_copy_isolates_post_copy_writes() -> None:
    """After copy, writes to either thread don't leak into the other."""
    saver = InMemorySaver()
    src_cfg = {"configurable": {"thread_id": "src", "checkpoint_ns": ""}}
    tgt_cfg = {"configurable": {"thread_id": "tgt", "checkpoint_ns": ""}}

    await saver.aput(src_cfg, _make_checkpoint("c0"), CheckpointMetadata(), {})
    await copy_thread_via_public_api(saver, "src", "tgt")

    # Add a new checkpoint to source — target must not see it.
    await saver.aput(src_cfg, _make_checkpoint("c1-src-only"), CheckpointMetadata(), {})
    # Add a different new checkpoint to target — source must not see it.
    await saver.aput(tgt_cfg, _make_checkpoint("c1-tgt-only"), CheckpointMetadata(), {})

    src_ids = sorted([t.checkpoint["id"] async for t in saver.alist(src_cfg)])
    tgt_ids = sorted([t.checkpoint["id"] async for t in saver.alist(tgt_cfg)])

    assert "c1-src-only" in src_ids and "c1-tgt-only" not in src_ids
    assert "c1-tgt-only" in tgt_ids and "c1-src-only" not in tgt_ids


@pytest.mark.asyncio
async def test_copy_works_when_source_has_metadata() -> None:
    """Metadata fields (source step, writes, etc.) survive the copy."""
    saver = InMemorySaver()
    src_cfg = {"configurable": {"thread_id": "src", "checkpoint_ns": ""}}
    md = CheckpointMetadata(source="loop", step=1, writes={"channel": "value"})
    await saver.aput(src_cfg, _make_checkpoint("c0"), md, {})

    await copy_thread_via_public_api(saver, "src", "tgt")

    tgt_cfg = {"configurable": {"thread_id": "tgt", "checkpoint_ns": ""}}
    tuples = [t async for t in saver.alist(tgt_cfg)]
    assert len(tuples) == 1
    assert tuples[0].metadata.get("step") == 1
    assert tuples[0].metadata.get("source") == "loop"
