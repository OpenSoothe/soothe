"""Tests for JobLoopIndex durable membership (IG-677)."""

from __future__ import annotations

import pytest

from soothe.autopilot.job_loop_index import JobLoopIndex


class _MemStore:
    def __init__(self) -> None:
        self.data: dict[str, object] = {}

    async def save(self, key: str, value: object) -> None:
        self.data[key] = value

    async def load(self, key: str) -> object | None:
        return self.data.get(key)

    async def delete(self, key: str) -> None:
        self.data.pop(key, None)

    async def list_keys(self) -> list[str]:
        return list(self.data.keys())


@pytest.mark.asyncio
async def test_record_start_and_end_round_trip() -> None:
    index = JobLoopIndex(store=_MemStore())
    await index.ensure_job("job1")
    entry = await index.record_start(
        "job1",
        loop_id="autopilot__job1__" + "a" * 32,
        goal_id="g1",
        attempt=1,
    )
    assert entry.seq == 1
    assert entry.status == "active"

    record = await index.get_job("job1")
    assert record is not None
    assert record.active_loops == [entry.loop_id]
    assert await index.owner_of(entry.loop_id) == "job1"

    ended = await index.record_end(entry.loop_id, status="completed")
    assert ended is not None
    assert ended.status == "completed"
    assert ended.ended_at is not None

    record2 = await index.get_job("job1")
    assert record2 is not None
    assert record2.active_loops == []


@pytest.mark.asyncio
async def test_seq_increments_across_assignments() -> None:
    index = JobLoopIndex()
    e1 = await index.record_start("j", loop_id="autopilot__j__" + "1" * 32, goal_id="a")
    e2 = await index.record_start("j", loop_id="autopilot__j__" + "2" * 32, goal_id="b")
    assert e1.seq == 1
    assert e2.seq == 2
    loops = await index.list_loops("j")
    assert len(loops) == 2


@pytest.mark.asyncio
async def test_interrupt_active_loops_on_restore() -> None:
    store = _MemStore()
    index = JobLoopIndex(store=store)
    await index.record_start("j", loop_id="autopilot__j__" + "c" * 32, goal_id="g")
    interrupted = await index.interrupt_active_loops()
    assert interrupted == ["autopilot__j__" + "c" * 32]
    record = await index.get_job("j")
    assert record is not None
    assert record.active_loops == []
    assert record.loops[0].status == "interrupted"


@pytest.mark.asyncio
async def test_in_memory_index_without_store() -> None:
    index = JobLoopIndex(store=None)
    await index.record_start("j", loop_id="L1", goal_id="g")
    assert await index.owner_of("L1") == "j"
    await index.record_end("L1", status="failed")
    assert (await index.list_loops("j"))[0].status == "failed"
