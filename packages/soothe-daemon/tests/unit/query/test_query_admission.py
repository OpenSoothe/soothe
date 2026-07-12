"""Tests for query admission control (IG-534 gaps)."""

from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest

from soothe_daemon.config.settings import SootheDaemonConfig
from soothe_daemon.query.engine import QueryAdmission, QueryEngine
from soothe_daemon.runtime.loop_broadcast_budget import LoopBroadcastBudget


class _FakeRunner:
    current_thread_id: str | None = None

    def set_current_thread_id(self, thread_id: str | None) -> None:
        self.current_thread_id = thread_id

    async def touch_thread_activity_timestamp(self, _thread_id: str) -> None:
        return None


class _FakeThreadRegistry:
    def get(self, _thread_id: str) -> None:
        return None

    def get_thread_loop(self, _thread_id: str) -> str | None:
        return None


def _daemon_factory(*, broadcasts: list[dict[str, Any]]) -> SimpleNamespace:
    async def _broadcast(msg: dict[str, Any]) -> None:
        broadcasts.append(msg)

    daemon_config = SootheDaemonConfig(max_concurrent_threads=100)

    return SimpleNamespace(
        _runner=_FakeRunner(),
        _runner_factory=SimpleNamespace(create_runner=lambda _key: None),
        _query_state_lock=asyncio.Lock(),
        _thread_registry=_FakeThreadRegistry(),
        _daemon_workspace=Path.cwd(),
        _thread_logger=SimpleNamespace(
            _thread_id="thread-1",
            log_user_input=lambda _text: None,
            log_assistant_response=lambda _text: None,
            log=lambda *_args, **_kwargs: None,
            flush=lambda: None,
        ),
        _config=SimpleNamespace(
            observability=SimpleNamespace(
                thread_logging_retention_days=7,
                thread_logging_max_size_mb=10,
            ),
            agent=SimpleNamespace(
                loop=SimpleNamespace(
                    output_streaming=SimpleNamespace(
                        adaptive_threshold_chars=500,
                        adaptive_block_chars=1024,
                        adaptive_block_interval_ms=250,
                        file_output_threshold_chars=0,
                        file_output_preview_chars=500,
                        file_output_dir=None,
                        streaming_interval_ms=300,
                        message_coalesce_enabled=True,
                        tool_batch_enabled=True,
                        tool_batch_interval_ms=200,
                        suppress_redundant_stream_tool_updates=True,
                        skip_redundant_tool_message_wire=False,
                    )
                )
            ),
        ),
        _daemon_config=daemon_config,
        _global_history=None,
        _active_threads={},
        _current_query_task=None,
        _active_stream_loop_ids=set(),
        _loops_with_active_query=set(),
        _loop_broadcast_budget=LoopBroadcastBudget(80),
        _broadcast=_broadcast,
        _session_manager=SimpleNamespace(
            claim_loop_ownership=lambda *_args, **_kwargs: None,
            release_loop_ownership=lambda *_args, **_kwargs: None,
            subscribe_loop=lambda *_args, **_kwargs: True,
            get_stream_delivery=lambda *_args, **_kwargs: "batch",
            get_clients_for_loop=AsyncMock(return_value=[]),
            get_loop_subscription_id=AsyncMock(return_value=None),
        ),
        _message_router=SimpleNamespace(_send_complete=lambda *_args, **_kwargs: None),
        _persistence_manager=SimpleNamespace(
            get_loop_metadata=AsyncMock(return_value={}),
        ),
    )


@pytest.mark.asyncio
async def test_second_query_on_same_loop_rejected() -> None:
    broadcasts: list[dict[str, Any]] = []
    daemon = _daemon_factory(broadcasts=broadcasts)
    engine = QueryEngine(daemon)

    assert (
        (await engine._admit_query(effective_loop_id="loop-a", thread_id="thread-1"))[0]
        is QueryAdmission.ADMITTED
    )
    assert (
        (await engine._admit_query(effective_loop_id="loop-a", thread_id="thread-2"))[0]
        is QueryAdmission.LOOP_BUSY
    )

    await engine._release_query_admission("loop-a")


@pytest.mark.asyncio
async def test_concurrent_queries_on_different_loops_admitted() -> None:
    daemon = _daemon_factory(broadcasts=[])
    engine = QueryEngine(daemon)

    first, _ = await engine._admit_query(effective_loop_id="loop-a", thread_id="thread-a")
    second, _ = await engine._admit_query(effective_loop_id="loop-b", thread_id="thread-b")

    assert first is QueryAdmission.ADMITTED
    assert second is QueryAdmission.ADMITTED
    assert daemon._loops_with_active_query == {"loop-a", "loop-b"}

    await engine._release_query_admission("loop-a")
    await engine._release_query_admission("loop-b")


@pytest.mark.asyncio
async def test_register_query_task_under_lock() -> None:
    daemon = _daemon_factory(broadcasts=[])
    engine = QueryEngine(daemon)

    async def noop() -> None:
        return None

    task = asyncio.create_task(noop())
    await engine._register_query_task("thread-1", task)
    assert daemon._active_threads["thread-1"] is task
    await task
    await engine._unregister_query_task("thread-1")
    assert "thread-1" not in daemon._active_threads
