"""QueryEngine stream termination ordering tests (IG-556 hardening)."""

from __future__ import annotations

import asyncio
import importlib.util
import json
from contextlib import suppress
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest
from soothe_sdk.core.events import STRANGE_LOOP_COMPLETED, STREAM_END

_ENGINE_CANCEL_PATH = Path(__file__).with_name("test_engine_cancel.py")
_ENGINE_CANCEL_SPEC = importlib.util.spec_from_file_location(
    "daemon_test_engine_cancel",
    _ENGINE_CANCEL_PATH,
)
assert _ENGINE_CANCEL_SPEC and _ENGINE_CANCEL_SPEC.loader
_ENGINE_CANCEL = importlib.util.module_from_spec(_ENGINE_CANCEL_SPEC)
_ENGINE_CANCEL_SPEC.loader.exec_module(_ENGINE_CANCEL)

QueryEngine = _ENGINE_CANCEL.QueryEngine
_daemon_factory = _ENGINE_CANCEL._daemon_factory

_GOLDEN_ENGINE = Path(__file__).with_name("golden") / "ig556_engine_turn_wire_trace.json"


class _CompletedTurnRunner:
    """Yields one goal_completion chunk then strange_loop.completed."""

    def __init__(self) -> None:
        self.current_thread_id = "thread-1"

    async def touch_thread_activity_timestamp(self, _thread_id: str) -> None:
        return None

    async def create_persisted_thread(self, thread_id: str | None = None) -> Any:
        del thread_id
        return SimpleNamespace(thread_id="thread-1")

    def set_current_thread_id(self, thread_id: str | None) -> None:
        self.current_thread_id = thread_id

    async def astream(self, _text: str, **_kwargs: Any):  # type: ignore[no-untyped-def]
        await asyncio.sleep(0.02)
        yield (
            (),
            "messages",
            (
                {
                    "type": "AIMessageChunk",
                    "content": "synthesis tail",
                    "phase": "goal_completion",
                },
                {},
            ),
        )
        yield ((), "custom", {"type": STRANGE_LOOP_COMPLETED, "status": "done"})


def _loop_broadcasts(broadcasts: list[dict[str, Any]], loop_id: str) -> list[dict[str, Any]]:
    return [msg for msg in broadcasts if msg.get("loop_id") == loop_id]


def _normalize_client_trace(
    broadcasts: list[dict[str, Any]],
    *,
    loop_id: str,
    drained: bool,
) -> list[dict[str, Any]]:
    """Reduce loop-scoped client frames to kind/type/scope for golden comparison."""

    def _append_event(trace: list[dict[str, Any]], msg: dict[str, Any]) -> None:
        if msg.get("type") != "event":
            return
        mode = msg.get("mode")
        data = msg.get("data")
        if mode == "messages" and isinstance(data, (tuple, list)) and data:
            body = data[0] if isinstance(data[0], dict) else {}
            trace.append(
                {
                    "kind": "messages",
                    "phase": body.get("phase"),
                    "stream_terminal": body.get("stream_terminal"),
                }
            )
        elif mode == "custom" and isinstance(data, dict):
            entry: dict[str, Any] = {
                "kind": "custom",
                "type": data.get("type"),
            }
            if "scope" in data:
                entry["scope"] = data.get("scope")
            if "reason" in data:
                entry["reason"] = data.get("reason")
            trace.append(entry)

    trace: list[dict[str, Any]] = []
    idle_entries: list[dict[str, Any]] = []
    for msg in _loop_broadcasts(broadcasts, loop_id):
        if msg.get("type") == "event_batch":
            for nested in msg.get("events") or []:
                if isinstance(nested, dict):
                    _append_event(trace, nested)
            continue
        if msg.get("type") == "status" and msg.get("state") == "idle":
            idle_entries.append({"kind": "lifecycle", "type": "idle"})
            continue
        _append_event(trace, msg)
    if drained:
        trace.append({"kind": "lifecycle", "type": "delivery_drained"})
    trace.extend(idle_entries)
    return trace


def _daemon_with_lifecycle_tracking(
    *,
    runner: Any,
    broadcasts: list[dict[str, Any]],
) -> tuple[SimpleNamespace, AsyncMock, list[str]]:
    lifecycle_order: list[str] = []

    async def _drain(*_args: Any, **_kwargs: Any) -> bool:
        lifecycle_order.append("drain")
        return True

    drain_mock = AsyncMock(side_effect=_drain)
    daemon = _daemon_factory(runner=runner, broadcasts=broadcasts)
    daemon._session_manager.await_loop_delivery_drained = drain_mock
    return daemon, drain_mock, lifecycle_order


@pytest.mark.asyncio
async def test_completed_turn_wire_trace_matches_golden() -> None:
    """Terminal → stream.end scopes → turn stream.end → drain → idle."""
    broadcasts: list[dict[str, Any]] = []
    runner = _CompletedTurnRunner()
    daemon, drain_mock, _lifecycle_order = _daemon_with_lifecycle_tracking(
        runner=runner,
        broadcasts=broadcasts,
    )
    engine = QueryEngine(daemon)

    await engine.run_query("finish turn", loop_id="loop-turn")
    task = daemon._current_query_task
    assert task is not None
    await task

    trace = _normalize_client_trace(
        broadcasts,
        loop_id="loop-turn",
        drained=drain_mock.await_count == 1,
    )
    expected = json.loads(_GOLDEN_ENGINE.read_text(encoding="utf-8"))
    assert trace == expected


@pytest.mark.asyncio
async def test_turn_stream_end_precedes_drain_and_idle() -> None:
    """Turn-scoped stream.end must be broadcast before idle."""
    broadcasts: list[dict[str, Any]] = []
    runner = _CompletedTurnRunner()
    daemon, _drain_mock, lifecycle_order = _daemon_with_lifecycle_tracking(
        runner=runner,
        broadcasts=broadcasts,
    )
    engine = QueryEngine(daemon)

    await engine.run_query("ordering", loop_id="loop-order")
    task = daemon._current_query_task
    assert task is not None
    await task

    loop_msgs = _loop_broadcasts(broadcasts, "loop-order")
    turn_end_ix = next(
        i
        for i, msg in enumerate(loop_msgs)
        if msg.get("type") == "event"
        and msg.get("mode") == "custom"
        and (msg.get("data") or {}).get("type") == STREAM_END
        and (msg.get("data") or {}).get("scope") == "turn"
    )
    idle_ix = next(
        i
        for i, msg in enumerate(loop_msgs)
        if msg.get("type") == "status" and msg.get("state") == "idle"
    )
    assert turn_end_ix < idle_ix
    assert lifecycle_order == ["drain"]


@pytest.mark.asyncio
async def test_cancel_emits_turn_stream_end_with_reason_before_idle() -> None:
    """Mid-stream cancel must emit turn stream.end (reason=cancelled) before idle."""
    slow_cancel_runner = _ENGINE_CANCEL._SlowCancelRunner

    broadcasts: list[dict[str, Any]] = []
    runner = slow_cancel_runner(unwind_delay=0.04)
    daemon, _drain_mock, _lifecycle_order = _daemon_with_lifecycle_tracking(
        runner=runner,
        broadcasts=broadcasts,
    )
    engine = QueryEngine(daemon)

    await engine.run_query("cancel mid stream", loop_id="loop-cancel-end")
    task = daemon._current_query_task
    assert task is not None
    daemon._thread_registry = _ENGINE_CANCEL._RegistryMapsThreadLoop(
        {"thread-1": "loop-cancel-end"}
    )
    await engine.cancel_loop("loop-cancel-end")
    with suppress(asyncio.CancelledError):
        await task

    loop_msgs = _loop_broadcasts(broadcasts, "loop-cancel-end")
    turn_ends = [
        msg
        for msg in loop_msgs
        if msg.get("type") == "event"
        and msg.get("mode") == "custom"
        and (msg.get("data") or {}).get("type") == STREAM_END
        and (msg.get("data") or {}).get("scope") == "turn"
    ]
    assert len(turn_ends) == 1
    assert turn_ends[0]["data"]["reason"] == "cancelled"

    turn_ix = loop_msgs.index(turn_ends[0])
    idle_ix = next(
        i
        for i, msg in enumerate(loop_msgs)
        if msg.get("type") == "status" and msg.get("state") == "idle"
    )
    assert turn_ix < idle_ix


@pytest.mark.asyncio
async def test_turn_frames_include_turn_id_and_seq() -> None:
    """Running / stream.end / idle carry turn_id and monotonic seq."""
    broadcasts: list[dict[str, Any]] = []
    runner = _CompletedTurnRunner()
    daemon, _drain_mock, _lifecycle_order = _daemon_with_lifecycle_tracking(
        runner=runner,
        broadcasts=broadcasts,
    )
    engine = QueryEngine(daemon)

    await engine.run_query("stamp turn", loop_id="loop-stamp")
    task = daemon._current_query_task
    assert task is not None
    await task

    loop_msgs = _loop_broadcasts(broadcasts, "loop-stamp")
    running = next(
        m for m in loop_msgs if m.get("type") == "status" and m.get("state") == "running"
    )
    idle = next(m for m in loop_msgs if m.get("type") == "status" and m.get("state") == "idle")
    turn_end = next(
        m
        for m in loop_msgs
        if m.get("type") == "event"
        and m.get("mode") == "custom"
        and (m.get("data") or {}).get("type") == STREAM_END
        and (m.get("data") or {}).get("scope") == "turn"
    )
    expected_tid = "loop-stamp:1"
    assert running.get("turn_id") == expected_tid
    assert idle.get("turn_id") == expected_tid
    assert turn_end.get("turn_id") == expected_tid
    assert (turn_end.get("data") or {}).get("turn_id") == expected_tid
    assert isinstance(running.get("seq"), int) and running["seq"] >= 1
    assert isinstance(idle.get("seq"), int) and idle["seq"] > running["seq"]
    assert isinstance(turn_end.get("seq"), int)
    assert running["seq"] < turn_end["seq"] < idle["seq"]


@pytest.mark.asyncio
async def test_await_loop_ready_waits_while_finalizing() -> None:
    """Next admit waits until prior finalize clears."""
    daemon = _daemon_factory(runner=_CompletedTurnRunner(), broadcasts=[])
    engine = QueryEngine(daemon)
    engine._loops_finalizing.add("loop-fin")

    async def _clear() -> None:
        await asyncio.sleep(0.05)
        engine._loops_finalizing.discard("loop-fin")

    clearer = asyncio.create_task(_clear())
    started = asyncio.get_running_loop().time()
    await engine.await_loop_ready_for_turn("loop-fin")
    elapsed = asyncio.get_running_loop().time() - started
    await clearer
    assert elapsed >= 0.04
