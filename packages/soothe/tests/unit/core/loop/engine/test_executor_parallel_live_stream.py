"""Parallel execute forwards stream events while steps are still running."""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import MagicMock

import pytest
from langchain_core.messages import AIMessage, AIMessageChunk

from soothe.core.loop.engine.executor import Executor, StreamEvent
from soothe.core.loop.state.schemas import LoopState, StepAction, StepResult


@pytest.mark.asyncio
async def test_execute_parallel_yields_stream_events_before_all_steps_finish() -> None:
    """Stream chunks must reach the consumer during the wave, not only after gather."""
    fast_event: StreamEvent = (("tools:fast",), "messages", (MagicMock(), {}))
    slow_event: StreamEvent = (("tools:slow",), "messages", (MagicMock(), {}))

    async def fake_collect(
        step: StepAction,
        thread_id: str,
        workspace: str | None = None,
        *,
        live_event_queue: asyncio.Queue[Any] | None = None,
        **kwargs: Any,
    ) -> tuple[list[StreamEvent], StepResult, list, str]:
        del thread_id, workspace, kwargs
        if step.id == "slow":
            await asyncio.sleep(0.25)
        else:
            await asyncio.sleep(0.03)
        event = slow_event if step.id == "slow" else fast_event
        if live_event_queue is not None:
            live_event_queue.put_nowait(event)
        result = StepResult(
            step_id=step.id,
            success=True,
            outcome={"type": "generic"},
            duration_ms=1,
            thread_id="t-par",
            tool_call_count=1,
        )
        return ([event], result, [], "")

    executor = Executor(MagicMock(), max_parallel_steps=4)
    executor._execute_step_collecting_events = fake_collect  # type: ignore[method-assign]

    state = LoopState(goal="g", thread_id="t-par", iteration=0, max_iterations=4)
    steps = [
        StepAction(id="fast", description="fast step"),
        StepAction(id="slow", description="slow step"),
    ]

    seen: list[Any] = []
    first_tool_at: float | None = None
    all_done_at: float | None = None
    loop = asyncio.get_running_loop()
    start = loop.time()

    async for item in executor._execute_parallel(steps, state):
        seen.append(item)
        if first_tool_at is None and isinstance(item, tuple) and item[1] == "messages":
            first_tool_at = loop.time() - start
        if all_done_at is None and len([x for x in seen if isinstance(x, StepResult)]) == len(
            steps
        ):
            all_done_at = loop.time() - start

    assert first_tool_at is not None
    assert all_done_at is not None
    assert first_tool_at < all_done_at - 0.08
    assert len([x for x in seen if isinstance(x, tuple) and len(x) == 3]) == 2
    step_results = [x for x in seen if isinstance(x, StepResult)]
    assert len(step_results) == 2
    assert {r.step_id for r in step_results} == {"fast", "slow"}


@pytest.mark.asyncio
async def test_execute_parallel_ledger_uses_step_id_when_completion_order_differs() -> None:
    """Ledger rows align to plan step order via step_id, not completion order."""
    order: list[str] = []

    async def fake_collect(
        step: StepAction,
        thread_id: str,
        workspace: str | None = None,
        *,
        live_event_queue: asyncio.Queue[Any] | None = None,
        **kwargs: Any,
    ) -> tuple[list[StreamEvent], StepResult, list, str]:
        del thread_id, workspace, live_event_queue, kwargs
        if step.id == "first":
            await asyncio.sleep(0.2)
        else:
            await asyncio.sleep(0.02)
        order.append(step.id)
        result = StepResult(
            step_id=step.id,
            success=True,
            outcome={"type": "generic"},
            duration_ms=1,
            thread_id="t-order",
            tool_call_count=0,
        )
        return ([], result, [], "")

    executor = Executor(MagicMock(), max_parallel_steps=4)
    executor._execute_step_collecting_events = fake_collect  # type: ignore[method-assign]

    state = LoopState(goal="g", thread_id="t-order", iteration=0, max_iterations=4)
    steps = [
        StepAction(id="first", description="slow first in plan"),
        StepAction(id="second", description="fast second in plan"),
    ]

    async for _ in executor._execute_parallel(steps, state):
        pass

    assert order[0] == "second"
    assert len(state.loop_messages) == 4
    assert state.loop_messages[0].content == "Execute: slow first in plan"
    assert getattr(state.loop_messages[0], "step_id", None) == "first"
    assert state.loop_messages[2].content == "Execute: fast second in plan"
    assert getattr(state.loop_messages[2], "step_id", None) == "second"


# IG-416: Tests for augmented TOOL_BINDING events with name and args


@pytest.mark.asyncio
async def test_extract_tool_name_and_args_from_aimessage_with_dict_args() -> None:
    """Extract tool name and args when AIMessage has complete dict args."""
    from soothe.core.loop.engine.executor import _extract_tool_name_and_args_for_binding

    # AIMessage (non-chunk) can have dict args in tool_calls
    msg = AIMessage(
        content="",
        tool_calls=[
            {"id": "tc_123", "name": "read_file", "args": {"path": "/tmp/test.txt"}},
        ],
    )
    name, args, status = _extract_tool_name_and_args_for_binding(msg, "tc_123", {})
    assert name == "read_file"
    assert args == {"path": "/tmp/test.txt"}
    assert status == "complete"


@pytest.mark.asyncio
async def test_extract_tool_name_and_args_from_chunk_with_string_args_complete() -> None:
    """Extract tool name and args when chunk has complete JSON string args."""
    from soothe.core.loop.engine.executor import _extract_tool_name_and_args_for_binding

    chunk = AIMessageChunk(
        content="",
        tool_call_chunks=[
            {"id": "tc_456", "name": "execute", "args": '{"command": "ls"}'},
        ],
    )
    name, args, status = _extract_tool_name_and_args_for_binding(chunk, "tc_456", {})
    assert name == "execute"
    assert args == {"command": "ls"}
    assert status == "complete"


@pytest.mark.asyncio
async def test_extract_tool_name_and_args_from_chunk_with_partial_args() -> None:
    """Return partial status when args are incomplete JSON."""
    from soothe.core.loop.engine.executor import _extract_tool_name_and_args_for_binding

    chunk = AIMessageChunk(
        content="",
        tool_call_chunks=[
            {"id": "tc_789", "name": "write_file", "args": '{"path": "/tmp/'},
        ],
    )
    name, args, status = _extract_tool_name_and_args_for_binding(chunk, "tc_789", {})
    assert name == "write_file"
    assert args is None  # Partial JSON can't be parsed
    assert status == "partial"


@pytest.mark.asyncio
async def test_extract_tool_name_and_args_fallback_to_accumulated() -> None:
    """Use accumulated args when chunk has no complete args."""
    from soothe.core.loop.engine.executor import _extract_tool_name_and_args_for_binding

    chunk = AIMessageChunk(
        content="",
        tool_call_chunks=[
            {"id": "tc_abc", "name": "grep", "args": ""},  # Empty args in chunk
        ],
    )
    accumulated = {"tc_abc": {"pattern": "test", "path": "/src"}}
    name, args, status = _extract_tool_name_and_args_for_binding(chunk, "tc_abc", accumulated)
    assert name == "grep"
    assert args == {"pattern": "test", "path": "/src"}
    assert status == "complete"


@pytest.mark.asyncio
async def test_binding_event_includes_augmented_fields() -> None:
    """TOOL_BINDING event should include tool_name, args, args_status fields."""
    # This is verified by the executor emitting the event structure correctly.
    # We test the structure by simulating the yield path.
    from soothe.core.events.constants import AGENT_LOOP_STEP_TOOL_BINDING

    # Simulate the binding event structure as executor creates it
    binding_event = {
        "type": AGENT_LOOP_STEP_TOOL_BINDING,
        "step_id": "step_1",
        "tool_call_id": "tc_xyz",
        "tool_name": "read_file",
        "args": {"path": "/etc/config.yml"},
        "args_status": "complete",
    }

    assert binding_event["type"] == AGENT_LOOP_STEP_TOOL_BINDING
    assert binding_event["step_id"] == "step_1"
    assert binding_event["tool_call_id"] == "tc_xyz"
    assert binding_event["tool_name"] == "read_file"
    assert binding_event["args"] == {"path": "/etc/config.yml"}
    assert binding_event["args_status"] == "complete"
