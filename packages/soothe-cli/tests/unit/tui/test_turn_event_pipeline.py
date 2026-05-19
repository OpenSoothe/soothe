"""Tests for TUI turn stream pipeline and background preparation."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from soothe_cli.events.turn.turn_event_pipeline import TurnEventPipeline, run_turn_pipeline
from soothe_cli.events.turn.turn_stream_prepare import TurnPrepareState, prepare_turn_chunk


@pytest.mark.asyncio
async def test_run_turn_pipeline_processes_chunks_in_order() -> None:
    """Reader, processor thread, and applier preserve chunk order."""
    received: list[Any] = []

    async def _source() -> Any:
        for item in [("ns", "custom", {"type": "soothe.test.event"}), ("", "updates", {})]:
            yield item

    def _process(raw: Any) -> tuple[Any, ...]:
        return tuple(raw)

    async def _apply(prepared: tuple[Any, ...]) -> None:
        received.append(prepared)

    await run_turn_pipeline(_source(), _process, _apply)

    assert len(received) == 2
    assert received[0][1] == "custom"
    assert received[1][1] == "updates"


def test_prepare_turn_chunk_skips_invisible_custom_events() -> None:
    """Custom events below the active verbosity tier are dropped in prepare."""
    from soothe_cli.events.core.presentation_engine import PresentationEngine
    from soothe_cli.tui._session_stats import TurnEventStats
    from soothe_cli.tui.step_task_routing import StepTaskRouter

    state = TurnPrepareState(
        ev_stats=TurnEventStats(),
        router=StepTaskRouter(),
        presentation=PresentationEngine(),
        pending_tool_calls_lc={},
        streaming_overlay={},
    )
    prepared = prepare_turn_chunk(
        state,
        (
            ("sub",),
            "custom",
            {"type": "soothe.debug.internal.trace", "message": "noise"},
        ),
    )
    assert prepared is not None
    assert prepared.skip is True


@pytest.mark.asyncio
async def test_pipeline_propagates_processor_errors() -> None:
    """Processor exceptions surface to the applier coroutine."""
    loop = asyncio.get_running_loop()
    pipeline: TurnEventPipeline[None] = TurnEventPipeline(loop)

    def _boom(_raw: Any) -> None:
        raise ValueError("processor failed")

    pipeline.start_processor(_boom)

    await asyncio.to_thread(pipeline._inbound.put, ("", "updates", {}))

    with pytest.raises(ValueError, match="processor failed"):
        async for _item in pipeline.iter_prepared():
            pass

    pipeline.shutdown()
