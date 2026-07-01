"""Tests for ThreadStateRegistry concurrency helpers."""

from __future__ import annotations

import threading

from soothe_daemon.runtime.thread_state import ThreadStateRegistry


def test_ensure_returns_same_instance_under_contention() -> None:
    registry = ThreadStateRegistry()
    states: list[object] = []
    barrier = threading.Barrier(8)

    def worker() -> None:
        barrier.wait()
        states.append(registry.ensure("thread-1", is_draft=True))

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert len({id(state) for state in states}) == 1
    assert registry.get("thread-1") is not None
