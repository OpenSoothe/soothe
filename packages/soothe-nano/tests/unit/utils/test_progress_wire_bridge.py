"""Tests for progress wire-bridge helpers."""

from __future__ import annotations

import asyncio
import contextvars
import logging

from soothe_nano.utils.progress import (
    emit_progress,
    get_wire_bridge,
    reset_wire_bridge,
    set_wire_bridge,
)


def test_emit_progress_uses_wire_bridge_exclusively() -> None:
    seen: list[dict[str, object]] = []

    def _sink(event: dict[str, object]) -> None:
        seen.append(event)

    token = set_wire_bridge(_sink)
    try:
        assert get_wire_bridge() is _sink
        emit_progress(
            {"type": "soothe.subagent.browser_use.step.completed", "tool_name": "Navigate"},
            logging.getLogger("test.progress"),
        )
    finally:
        reset_wire_bridge(token)

    assert len(seen) == 1
    assert seen[0]["tool_name"] == "Navigate"
    assert get_wire_bridge() is None


def test_emit_progress_uses_loop_bridge_when_context_missing() -> None:
    seen: list[dict[str, object]] = []

    def _sink(event: dict[str, object]) -> None:
        seen.append(event)

    async def _run() -> None:
        token = set_wire_bridge(_sink)
        try:
            fresh_context = contextvars.Context()

            async def _emit_from_fresh_context() -> None:
                emit_progress(
                    {
                        "type": "soothe.subagent.browser_use.step.completed",
                        "tool_name": "Click",
                    },
                    logging.getLogger("test.progress.context-loss"),
                )

            task = asyncio.create_task(_emit_from_fresh_context(), context=fresh_context)
            await task
        finally:
            reset_wire_bridge(token)

    asyncio.run(_run())
    assert len(seen) == 1
    assert seen[0]["tool_name"] == "Click"
