"""Tests for abbreviated large-paste display in chat input."""

from __future__ import annotations

from soothe_cli.tui.input import (
    abbreviate_pasted_input_display,
    should_abbreviate_pasted_input,
)

_TRACE_SAMPLE = """\
│   694 │
│   695 │   async def request_daemon_ready(self) -> None:
│ ❱ 697 │   │   await self.send({"type": "daemon_ready"})
│   698 │
│   699 │   async def wait_for_daemon_ready(self, ready_timeout_s: float = 10.0) -> dict[str, :
│   700 │   │   \"\"\"Wait for a daemon readiness message and require ready state.
ConnectionError: Connection closed
"""


def test_should_abbreviate_long_multiline_paste() -> None:
    assert should_abbreviate_pasted_input(_TRACE_SAMPLE) is True


def test_should_not_abbreviate_short_paste() -> None:
    assert should_abbreviate_pasted_input("fix the websocket bug") is False


def test_abbreviate_shows_header_and_omitted_line_count() -> None:
    display = abbreviate_pasted_input_display(_TRACE_SAMPLE)
    assert display.startswith("[pasted ")
    assert "lines," in display
    assert "characters]" in display
    assert "more lines" in display
    assert "ConnectionError: Connection closed" in display
    assert "request_daemon_ready" in display
    assert len(display) < len(_TRACE_SAMPLE)


def test_abbreviate_preserves_full_text_separately() -> None:
    """Display is shorter; callers keep the original payload for submit."""
    display = abbreviate_pasted_input_display(_TRACE_SAMPLE)
    assert display != _TRACE_SAMPLE
    assert _TRACE_SAMPLE.strip() not in {display.strip()}
