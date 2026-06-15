"""Tests for abbreviated large-paste display in chat input."""

from __future__ import annotations

from soothe_cli.tui.input import (
    abbreviate_pasted_input_display,
    compose_paste_into_input,
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


def test_abbreviate_shows_header_only() -> None:
    display = abbreviate_pasted_input_display(_TRACE_SAMPLE)
    expected = f"[pasted {len(_TRACE_SAMPLE.splitlines())} lines, {len(_TRACE_SAMPLE)} characters]"
    assert display == expected
    assert len(display) < len(_TRACE_SAMPLE)


def test_abbreviate_preserves_full_text_separately() -> None:
    """Display is shorter; callers keep the original payload for submit."""
    display = abbreviate_pasted_input_display(_TRACE_SAMPLE)
    assert display != _TRACE_SAMPLE
    assert _TRACE_SAMPLE.strip() not in {display.strip()}


def test_compose_paste_into_input_appends_at_end_by_default() -> None:
    assert compose_paste_into_input("/skill:refine ", "summarize this trace") == (
        "/skill:refine summarize this trace"
    )


def test_compose_paste_into_input_inserts_at_cursor_offset() -> None:
    assert (
        compose_paste_into_input(
            "/skill:refine ",
            "please ",
            replace_start=7,
            replace_end=7,
        )
        == "/skill:please refine "
    )


def test_compose_paste_into_input_replaces_selected_span() -> None:
    assert (
        compose_paste_into_input(
            "/skill:refine old prompt",
            "new prompt",
            replace_start=14,
            replace_end=24,
        )
        == "/skill:refine new prompt"
    )


def test_abbreviated_preview_can_keep_selected_skill_visible() -> None:
    summary = abbreviate_pasted_input_display(_TRACE_SAMPLE)
    preview = compose_paste_into_input("/skill:platonic-brainstorming ", summary)
    assert preview.startswith("/skill:platonic-brainstorming ")
    assert summary in preview
