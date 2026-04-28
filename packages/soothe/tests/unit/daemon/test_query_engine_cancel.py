"""Regression tests for daemon query cancellation behavior."""

from __future__ import annotations

import asyncio
from contextlib import suppress
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from soothe.daemon.query_engine import QueryEngine


class _FakeRunner:
    def __init__(self) -> None:
        self.current_thread_id = "thread-1"

    async def touch_thread_activity_timestamp(self, _thread_id: str) -> None:
        return None

    async def create_persisted_thread(self, thread_id: str | None = None) -> Any:
        del thread_id
        return SimpleNamespace(thread_id="thread-1")

    def set_current_thread_id(self, thread_id: str | None) -> None:
        self.current_thread_id = thread_id

    def set_interrupt_resolver(self, _resolver: Any) -> None:
        return None

    async def astream(self, _text: str, **_kwargs: Any):  # type: ignore[override]
        raise asyncio.CancelledError
        yield  # pragma: no cover


class _FakeThreadRegistry:
    def get(self, _thread_id: str) -> None:
        return None

    def get_workspace(self, _thread_id: str) -> Path:
        return Path.cwd()

    def ensure(self, _thread_id: str, *, is_draft: bool = False) -> None:
        del is_draft

    def set_workspace(self, _thread_id: str, _workspace: Path) -> None:
        return None


@pytest.mark.asyncio
async def test_cancelled_query_does_not_emit_custom_error_event() -> None:
    """Cancelled turns should only update status, not emit stale cancel error events."""
    broadcasts: list[dict[str, Any]] = []

    async def _broadcast(msg: dict[str, Any]) -> None:
        broadcasts.append(msg)

    daemon = SimpleNamespace(
        _thread_executor=None,
        _runner=_FakeRunner(),
        _thread_registry=_FakeThreadRegistry(),
        _daemon_workspace=Path.cwd(),
        _thread_logger=SimpleNamespace(
            _thread_id="thread-1",
            log_user_input=lambda _text: None,
            log_assistant_response=lambda _text: None,
        ),
        _config=SimpleNamespace(
            daemon=SimpleNamespace(max_query_duration_minutes=0, max_concurrent_threads=100),
            logging=SimpleNamespace(
                thread_logging=SimpleNamespace(retention_days=7, max_size_mb=10)
            ),
            workspace_dir=".",
        ),
        _global_history=None,
        _active_threads={},
        _query_running=False,
        _current_query_task=None,
        _pending_interrupt_responses={},
        _broadcast=_broadcast,
        _session_manager=SimpleNamespace(
            claim_thread_ownership=lambda *_args, **_kwargs: None,
            release_thread_ownership=lambda *_args, **_kwargs: None,
            subscribe_thread=lambda *_args, **_kwargs: True,
        ),
    )

    engine = QueryEngine(daemon)
    await engine.run_query("cancel me")

    task = daemon._current_query_task
    assert task is not None
    with suppress(asyncio.CancelledError):
        await task

    custom_errors = [
        msg
        for msg in broadcasts
        if msg.get("type") == "event"
        and msg.get("mode") == "custom"
        and isinstance(msg.get("data"), dict)
        and str(msg["data"].get("error", "")).startswith("Query cancelled")
    ]
    assert custom_errors == []
