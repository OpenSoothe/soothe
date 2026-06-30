"""Tests for ``_StreamCollectChunk`` wire/finalized factory helpers."""

from __future__ import annotations

from langchain_core.messages import ToolMessage

from soothe.foundation.loop.engine.step_wave_types import _StreamCollectChunk


def test_wire_event_sets_event_only() -> None:
    event = (("tools:sub"), "custom", {"type": "tool_call_update"})
    chunk = _StreamCollectChunk.wire_event(event)
    assert chunk.event == event
    assert chunk.output is None
    assert chunk.main_tool_count == 0
    assert chunk.subgraph_tool_count == 0


def test_finalized_sets_summary_fields() -> None:
    msg = ToolMessage(content="ok", tool_call_id="x", name="grep")
    chunk = _StreamCollectChunk.finalized(
        output="combined",
        main_tool_count=2,
        messages=[msg],
        delegate_final="delegate text",
        outcomes=[{"type": "grep"}],
        has_error=False,
        subgraph_tool_count=5,
    )
    assert chunk.output == "combined"
    assert chunk.event is None
    assert chunk.main_tool_count == 2
    assert chunk.subgraph_tool_count == 5
    assert chunk.messages == (msg,)
    assert chunk.delegate_final == "delegate text"
    assert chunk.outcomes == ({"type": "grep"},)
