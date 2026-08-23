"""Tests for protocol-1 error envelope handling in TUI session and headless processor.

Protocol-1 wraps error details in a nested ``error`` object:
``{type:'error', error:{code, message, data}}``. The legacy format had
``message`` at the top level: ``{type:'error', message:'...'}``.

Both the TUI session's ``iter_turn_chunks`` and the headless ``EventProcessor``
must handle both formats during the migration window.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

from soothe_cli.runtime.headless.processor import EventProcessor


class _StubClient:
    """Minimal WebSocket client stub for TuiDaemonSession event reading."""

    def __init__(self, events: list[dict[str, Any] | None]) -> None:
        self._events = list(events)

    def peel_stale_pending_control_events(self) -> list[str]:
        return []

    def is_connection_alive(self) -> bool:
        return True

    async def read_event(self) -> dict[str, Any] | None:
        if not self._events:
            return None
        return self._events.pop(0)


# ---------------------------------------------------------------------------
# EventProcessor error handling
# ---------------------------------------------------------------------------


class _RecordingRenderer:
    """Renderer stub that captures error calls."""

    def __init__(self) -> None:
        self.errors: list[tuple[str, Any]] = []

    def on_error(self, error: str, *, context: Any = None) -> None:
        self.errors.append((error, context))


def _make_processor() -> tuple[EventProcessor, _RecordingRenderer]:
    renderer = _RecordingRenderer()
    processor = EventProcessor(
        renderer,  # type: ignore[arg-type]
        presentation_engine=MagicMock(),
        headless_output=True,
    )
    return processor, renderer


def test_processor_handles_legacy_flat_error() -> None:
    """Legacy error: {type:'error', message:'boom'}."""
    processor, renderer = _make_processor()
    processor.process_event({"type": "error", "message": "boom"})
    assert len(renderer.errors) == 1
    assert renderer.errors[0][0] == "boom"


def test_processor_handles_protocol1_error_envelope() -> None:
    """Protocol-1 error: {type:'error', error:{code, message, data}}."""
    processor, renderer = _make_processor()
    processor.process_event(
        {
            "type": "error",
            "error": {
                "code": -32200,
                "message": "Loop not found",
                "data": {"loop_id": "abc"},
            },
        }
    )
    assert len(renderer.errors) == 1
    assert renderer.errors[0][0] == "Loop not found"
    assert renderer.errors[0][1] == -32200


def test_processor_handles_bare_string_error() -> None:
    """Fallback: error field is a bare string (not a dict)."""
    processor, renderer = _make_processor()
    processor.process_event({"type": "error", "error": "something broke"})
    assert len(renderer.errors) == 1
    assert "something broke" in renderer.errors[0][0]


# ---------------------------------------------------------------------------
# TuiDaemonSession error handling in iter_turn_chunks
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_session_iter_turn_chunks_raises_on_protocol1_error() -> None:
    """iter_turn_chunks should raise RuntimeError with the nested message."""
    from soothe_cli.runtime.transport.session import TuiDaemonSession

    session = object.__new__(TuiDaemonSession)
    session._client = _StubClient(
        [
            {
                "type": "error",
                "error": {
                    "code": -32603,
                    "message": "Internal daemon error",
                    "data": {},
                },
            },
        ]
    )
    session._read_lock = __import__("asyncio").Lock()
    session._loop_id = "loop-test"
    session._streaming = False
    session.turn_event_stats = MagicMock()

    chunks: list[Any] = []
    with pytest.raises(RuntimeError, match="Internal daemon error"):
        async for chunk in session.iter_turn_chunks():
            chunks.append(chunk)
    assert chunks == []


@pytest.mark.asyncio
async def test_session_iter_turn_chunks_raises_on_legacy_error() -> None:
    """iter_turn_chunks should still handle legacy flat errors."""
    from soothe_cli.runtime.transport.session import TuiDaemonSession

    session = object.__new__(TuiDaemonSession)
    session._client = _StubClient([{"type": "error", "message": "legacy boom"}])
    session._read_lock = __import__("asyncio").Lock()
    session._loop_id = "loop-test"
    session._streaming = False
    session.turn_event_stats = MagicMock()

    with pytest.raises(RuntimeError, match="legacy boom"):
        async for _ in session.iter_turn_chunks():
            pass
