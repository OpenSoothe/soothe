"""Regression tests for legacy assistant-row composition in QueryEngine.

Loop 97bf incident: ``full_response`` accumulated ``ToolMessage`` content
(including langgraph's "Error invoking tool ..." error bodies) because
``extract_text_from_ai_message`` extracts plain-string content from any
message. The legacy assistant row then surfaced tool output and raw error
text as the user-visible assistant message. Only AI-message text may
compose the assistant row.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest
from langchain_core.messages import AIMessageChunk, ToolMessage

from soothe_daemon.config import SootheDaemonConfig
from soothe_daemon.query import QueryEngine
from soothe_daemon.runtime.loop_broadcast_budget import LoopBroadcastBudget


class _StreamingRunner:
    """Yields a fixed messages-mode chunk list."""

    def __init__(self, chunks: list[tuple[tuple[str, ...], str, Any]]) -> None:
        self._chunks = chunks
        self.current_thread_id = "thread-1"

    async def touch_thread_activity_timestamp(self, _thread_id: str) -> None:
        return None

    async def create_persisted_thread(self, thread_id: str | None = None) -> Any:
        del thread_id
        return SimpleNamespace(thread_id="thread-1")

    def set_current_thread_id(self, thread_id: str | None) -> None:
        self.current_thread_id = thread_id

    async def astream(self, _text: str, **_kwargs: Any):  # type: ignore[override]
        for chunk in self._chunks:
            yield chunk


class _FakeLoopRunner:
    def __init__(self, runner: _StreamingRunner) -> None:
        self._runner = runner

    async def run(self, _request: Any) -> Any:  # type: ignore[override]
        async for chunk in self._runner.astream(""):
            yield chunk

    async def cancel(self) -> None:
        return None


class _FakeRunnerFactory:
    def __init__(self, runner: _StreamingRunner) -> None:
        self._runner = runner

    def create_runner(self, loop_id: str) -> _FakeLoopRunner:  # noqa: ARG002
        return _FakeLoopRunner(self._runner)


class _FakeThreadRegistry:
    def get(self, _thread_id: str) -> None:
        return None

    def get_thread_loop(self, _thread_id: str) -> str:
        return ""

    def get_workspace(self, _thread_id: str) -> Path:
        return Path.cwd()

    def ensure(self, _thread_id: str, *, is_draft: bool = False) -> None:
        del is_draft

    def set_workspace(self, _thread_id: str, _workspace: Path) -> None:
        return None


class _FakePersistenceManager:
    async def get_loop_metadata(self, _loop_id: str) -> dict[str, Any] | None:
        return None


def _daemon_factory(
    *,
    runner: _StreamingRunner,
    assistant_rows: list[str],
) -> SimpleNamespace:
    async def _broadcast(msg: dict[str, Any]) -> None:
        del msg

    daemon_config = SootheDaemonConfig(
        max_query_duration_minutes=0,
        max_concurrent_threads=100,
        cancel_retry_count=1,
        cancel_retry_interval_seconds=0.5,
        cancel_force_kill_timeout_seconds=5.0,
    )

    return SimpleNamespace(
        _runner=runner,
        _runner_factory=_FakeRunnerFactory(runner),
        _query_state_lock=asyncio.Lock(),
        _thread_registry=_FakeThreadRegistry(),
        _daemon_workspace=Path.cwd(),
        _thread_logger=SimpleNamespace(
            _thread_id="thread-1",
            log_user_input=lambda _text: None,
            log_assistant_response=assistant_rows.append,
            log=lambda *_args, **_kwargs: None,
            flush=lambda: None,
        ),
        _config=SimpleNamespace(
            logging=SimpleNamespace(
                thread_logging=SimpleNamespace(retention_days=7, max_size_mb=10)
            ),
            workspace_dir=".",
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
            await_loop_delivery_drained=AsyncMock(return_value=True),
        ),
        _message_router=SimpleNamespace(),
        _persistence_manager=_FakePersistenceManager(),
    )


@pytest.mark.asyncio
async def test_legacy_assistant_row_excludes_tool_messages() -> None:
    """Tool output and error bodies must never reach the assistant row."""
    assistant_rows: list[str] = []
    runner = _StreamingRunner(
        [
            (
                (),
                "messages",
                (
                    ToolMessage(
                        content="User answered:\nQ: topic?\nA: Project priorities",
                        name="ask_user",
                        tool_call_id="t1",
                    ),
                    {},
                ),
            ),
            (
                (),
                "messages",
                (
                    ToolMessage(
                        content=(
                            "Error invoking tool 'ask_user' with kwargs {'header': "
                            "'Priority #1'} with error:\n questions.0.question: "
                            "Field required\n Please fix the error and try again."
                        ),
                        name="ask_user",
                        tool_call_id="t2",
                        status="error",
                    ),
                    {},
                ),
            ),
            ((), "messages", (AIMessageChunk(content="Here is the final answer."), {})),
        ]
    )
    daemon = _daemon_factory(runner=runner, assistant_rows=assistant_rows)
    engine = QueryEngine(daemon)

    await engine.run_query("ask me two questions and collect my answers", loop_id="loop-assist")

    assert assistant_rows == ["Here is the final answer."]


@pytest.mark.asyncio
async def test_legacy_assistant_row_omitted_without_ai_text() -> None:
    """A tool-only turn (e.g. parked clarification) writes no assistant row."""
    assistant_rows: list[str] = []
    runner = _StreamingRunner(
        [
            (
                (),
                "messages",
                (
                    ToolMessage(
                        content="User answered:\nQ: topic?\nA: Project priorities",
                        name="ask_user",
                        tool_call_id="t1",
                    ),
                    {},
                ),
            ),
        ]
    )
    daemon = _daemon_factory(runner=runner, assistant_rows=assistant_rows)
    engine = QueryEngine(daemon)

    await engine.run_query("ask me two questions and collect my answers", loop_id="loop-assist")

    assert assistant_rows == []
