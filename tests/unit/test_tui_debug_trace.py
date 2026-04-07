"""TUI debug trace logging (SOOTHE_TUI_DEBUG / IG-129)."""

from __future__ import annotations

import logging

import pytest

from soothe.ux.shared.event_processor import EventProcessor
from soothe.ux.tui.renderer import TuiRenderer
from tests.unit.test_event_processor import MockRenderer


@pytest.fixture
def trace_caplog(caplog: pytest.LogCaptureFixture) -> pytest.LogCaptureFixture:
    caplog.set_level(logging.INFO, logger="soothe.ux.tui.trace")
    return caplog


def test_tui_renderer_emits_trace_when_debug(trace_caplog: pytest.LogCaptureFixture) -> None:
    r = TuiRenderer(on_panel_write=lambda _x: None, tui_debug=True)
    r.on_assistant_text("hello", is_main=True, is_streaming=False)
    assert "tui_trace | renderer.assistant_text" in trace_caplog.text


def test_tui_renderer_silent_when_debug_off(trace_caplog: pytest.LogCaptureFixture) -> None:
    r = TuiRenderer(on_panel_write=lambda _x: None, tui_debug=False)
    r.on_assistant_text("hello", is_main=True, is_streaming=False)
    assert "tui_trace" not in trace_caplog.text


def test_event_processor_emits_trace_on_status(trace_caplog: pytest.LogCaptureFixture) -> None:
    renderer = MockRenderer()
    processor = EventProcessor(renderer, tui_debug=True)
    processor.process_event({"type": "status", "state": "running", "thread_id": "t1"})
    assert "tui_trace | processor.process_event" in trace_caplog.text
    assert "tui_trace | processor.status" in trace_caplog.text


def test_event_processor_messages_and_emit_trace(trace_caplog: pytest.LogCaptureFixture) -> None:
    renderer = MockRenderer()
    processor = EventProcessor(renderer, tui_debug=True, verbosity="normal")
    processor.process_event(
        {
            "type": "event",
            "mode": "messages",
            "namespace": [],
            "data": [
                {
                    "type": "AIMessage",
                    "id": "trace-msg-1",
                    "content": "Trace test body for TUI debug.",
                },
                {},
            ],
        }
    )
    text = trace_caplog.text
    assert "tui_trace | processor.stream_event" in text
    assert "tui_trace | processor.messages" in text
    assert "msg_kind='AIMessage'" in text
    assert "tui_trace | processor.emit_assistant_text" in text


def test_event_processor_messages_subgraph_namespace(trace_caplog: pytest.LogCaptureFixture) -> None:
    renderer = MockRenderer()
    processor = EventProcessor(renderer, tui_debug=True, verbosity="normal")
    processor.process_event(
        {
            "type": "event",
            "mode": "messages",
            "namespace": ["tools", "claude_subagent"],
            "data": [
                {
                    "type": "AIMessage",
                    "id": "trace-msg-sub",
                    "content": "Nested graph reply.",
                },
                {},
            ],
        }
    )
    assert "namespace=('tools', 'claude_subagent')" in trace_caplog.text
    assert "is_main=False" in trace_caplog.text
