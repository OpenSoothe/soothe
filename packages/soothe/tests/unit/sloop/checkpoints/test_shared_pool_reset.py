"""Regression tests for the shared PostgreSQL pool reset/await path.

Covers the loop-0041 "Shared checkpoint pool not initialized" failure:
``for_shared_checkpoint_pool`` used a synchronous ``get_pool()`` snapshot, so a
caller arriving during ``reset_pool``'s reopen window (when ``_pool`` is
transiently ``None``) raised ``RuntimeError`` and killed the loop.
``reset_pool`` also deadlocked re-entering ``open`` on the non-reentrant
``asyncio.Lock``.
"""

from __future__ import annotations

import asyncio

import pytest

from soothe.sloop.checkpoints.shared_pool import SharedPostgreSQLPool


class _FakePool:
    """Minimal AsyncConnectionPool stand-in."""

    def __init__(self) -> None:
        self.closed = False

    async def open(self) -> None:
        self.closed = False

    async def close(self) -> None:
        self.closed = True


def _make_wrapper() -> SharedPostgreSQLPool:
    wrapper = SharedPostgreSQLPool(dsn="postgresql://x/y", pool_size=1)
    wrapper._pool = _FakePool()
    wrapper._pool.closed = False
    wrapper._initialized = True
    return wrapper


@pytest.mark.asyncio
async def test_await_pool_returns_pool_when_initialized() -> None:
    """No reset in flight → await_pool returns the live pool immediately."""
    wrapper = _make_wrapper()
    live = wrapper._pool

    result = await wrapper.await_pool()
    assert result is live
    await wrapper._pool.close()


@pytest.mark.asyncio
async def test_await_pool_waits_through_reset_to_see_reopened_pool(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Caller arriving mid-reset blocks until reopen completes, sees new pool.

    Reproduces the loop-0041 window: before the fix, a concurrent caller
    snapshotted ``get_pool() is None`` during reopen and raised. With
    ``await_pool`` it must block on ``_init_lock`` and return the reopened pool.
    """
    wrapper = _make_wrapper()
    first_pool = wrapper._pool

    reopened = _FakePool()

    open_calls: list[_FakePool] = []

    async def _fake_open_locked(self: SharedPostgreSQLPool) -> _FakePool:
        # Emulate the reopen body: replace the pool and mark initialized.
        self._pool = reopened
        self._initialized = True
        open_calls.append(reopened)
        return reopened

    monkeypatch.setattr(SharedPostgreSQLPool, "_open_locked", _fake_open_locked)

    seen_during_reset: list[object] = []

    async def _reader() -> _FakePool:
        result = await wrapper.await_pool()
        # Must not observe the transiently-None window.
        seen_during_reset.append(result)
        return result  # type: ignore[return-value]

    async def _reset() -> None:
        await wrapper.reset_pool()

    reset_task = asyncio.create_task(_reset())
    reader_task = asyncio.create_task(_reader())

    result = await asyncio.wait_for(reader_task, timeout=2.0)
    await reset_task

    assert result is reopened
    assert reopened in seen_during_reset
    assert first_pool is not reopened
    assert open_calls == [reopened]
    # The old pool was closed during reset.
    assert first_pool.closed is True


@pytest.mark.asyncio
async def test_reset_pool_does_not_deadlock_on_reentry(monkeypatch: pytest.MonkeyPatch) -> None:
    """reset_pool must not re-enter open() on the non-reentrant asyncio.Lock.

    Before IG-706, reset_pool held ``_init_lock`` and called ``self.open()``,
    which re-acquires ``_init_lock`` → permanent deadlock (asyncio.Lock is not
    reentrant). The fix routes reopen through ``_open_locked`` instead.
    """
    wrapper = _make_wrapper()
    first_pool = wrapper._pool

    reopened = _FakePool()
    open_locked_calls: list[SharedPostgreSQLPool] = []

    real_open_locked = SharedPostgreSQLPool._open_locked

    async def _spy_open_locked(self: SharedPostgreSQLPool) -> _FakePool:
        open_locked_calls.append(self)
        self._pool = reopened
        self._initialized = True
        return reopened

    monkeypatch.setattr(SharedPostgreSQLPool, "_open_locked", _spy_open_locked)
    # Guard: if reset_pool ever re-enters open(), open()'s lock acquire hangs
    # and this timeout trips — the original deadlock.
    monkeypatch.setattr(SharedPostgreSQLPool, "open", real_open_locked)  # noqa: B010

    await asyncio.wait_for(wrapper.reset_pool(), timeout=2.0)

    assert open_locked_calls == [wrapper]
    assert wrapper._pool is reopened
    assert wrapper._initialized is True
    assert first_pool.closed is True


@pytest.mark.asyncio
async def test_for_shared_checkpoint_pool_survives_concurrent_reset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """for_shared_checkpoint_pool must not raise during a concurrent reset.

    Regression for loop 0041: the manager used ``get_pool()`` + None-check and
    raised RuntimeError when reset had nulled the pool. Now it uses
    ``await_pool`` and waits for reopen.
    """
    pytest.importorskip("psycopg")
    from soothe.config import SootheConfig
    from soothe.config.models import PersistenceConfig
    from soothe.sloop.checkpoints.manager import (
        StrangeLoopCheckpointPersistenceManager,
    )

    cfg = SootheConfig(
        persistence=PersistenceConfig(
            default_backend="postgresql",
            postgres_base_dsn="postgresql://postgres:postgres@localhost:5432",
        ),
        agent={
            "protocols": {"durability": {"backend": "postgresql", "checkpointer": "postgresql"}}
        },
    )

    wrapper = _make_wrapper()
    first_pool = wrapper._pool
    reopened = _FakePool()

    async def _fake_get_shared_instance(cls: type, config: SootheConfig) -> SharedPostgreSQLPool:
        return wrapper

    async def _fake_open_locked(self: SharedPostgreSQLPool) -> _FakePool:
        self._pool = reopened
        self._initialized = True
        return reopened

    monkeypatch.setattr(
        SharedPostgreSQLPool, "get_shared_instance", classmethod(_fake_get_shared_instance)
    )
    monkeypatch.setattr(SharedPostgreSQLPool, "_open_locked", _fake_open_locked)
    # Suppress the LoopPersistenceWriter side effect inside reset_pool.
    monkeypatch.setattr(
        "soothe.persistence.loop_writer.LoopPersistenceWriter.existing_instance",
        lambda: None,
    )

    async def _build_manager() -> None:
        await StrangeLoopCheckpointPersistenceManager.for_shared_checkpoint_pool(cfg)

    reset_task = asyncio.create_task(wrapper.reset_pool())
    build_task = asyncio.create_task(_build_manager())

    # Must not raise "Shared checkpoint pool not initialized".
    await asyncio.wait_for(build_task, timeout=2.0)
    await reset_task

    assert wrapper._pool is reopened
    assert first_pool.closed is True
