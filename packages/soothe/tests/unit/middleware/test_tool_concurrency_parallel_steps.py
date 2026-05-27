"""Tests for per-step tool concurrency isolation during parallel execute."""

from __future__ import annotations

import asyncio

import pytest

from soothe.middleware.tool_concurrency import (
    get_tool_semaphore,
    init_tool_concurrency_for_thread,
)


@pytest.mark.asyncio
async def test_parallel_tasks_each_get_independent_tool_semaphore() -> None:
    """Parallel execute steps should not share one Semaphore instance."""
    seen: list[int | None] = []

    async def worker(limit: int) -> None:
        init_tool_concurrency_for_thread(limit)
        sem = get_tool_semaphore()
        seen.append(id(sem))

    await asyncio.gather(worker(7), worker(7))

    assert len(seen) == 2
    assert seen[0] != seen[1]
