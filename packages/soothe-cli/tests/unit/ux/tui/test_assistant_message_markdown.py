"""Tests for AssistantMessage markdown rendering and flush behavior."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from soothe_cli.tui.markdown_theme import ThemedMarkdownRenderer
from soothe_cli.tui.widgets.messages import (
    AssistantMessage,
    _rich_style_with_textual_selection,
    _SelectableMarkdownBody,
)


def test_rich_style_with_textual_selection_blends_backgrounds() -> None:
    """Markdown selection must alpha-blend, not replace code-block backgrounds."""
    from rich.style import Style as RichStyle
    from textual.color import Color

    code_bg = RichStyle(bgcolor="#282a36")
    selection_bg = Color(1, 120, 212, 0.5)

    merged = _rich_style_with_textual_selection(code_bg, selection_bg)
    naive = code_bg + RichStyle(bgcolor="#094472")

    assert merged.bgcolor is not None
    assert naive.bgcolor is not None
    assert merged.bgcolor != naive.bgcolor


@pytest.mark.asyncio
async def test_constructor_render_markdown_override_disables_rich_markdown() -> None:
    """Explicit ``render_markdown=False`` renders plain text even when config enables MD."""
    msg = AssistantMessage(
        "I will complete this goal directly: read file",
        id="asst-test",
        render_markdown=False,
    )
    assert msg._render_markdown is False
    body = MagicMock()
    msg._body = body

    await msg.stop_stream()

    body.update.assert_called_with("I will complete this goal directly: read file")
    for call in body.update.call_args_list:
        assert not isinstance(call.args[0], ThemedMarkdownRenderer)


@pytest.mark.asyncio
async def test_stop_stream_renders_themed_markdown_to_body() -> None:
    """stop_stream() renders final content via configured markdown theme."""
    msg = AssistantMessage(id="asst-test")
    msg._content = "```python\nprint('hello')\n```"
    msg._streaming_active = True
    msg._render_markdown = True
    body = MagicMock()
    msg._body = body

    await msg.stop_stream()

    assert not msg._streaming_active
    body.update.assert_called_once()
    call_arg = body.update.call_args[0][0]
    assert isinstance(call_arg, ThemedMarkdownRenderer)


@pytest.mark.asyncio
async def test_stop_stream_renders_plain_text_when_markdown_disabled() -> None:
    """stop_stream() renders plain text when render_markdown is False."""
    msg = AssistantMessage(id="asst-test")
    msg._content = "Hello world"
    msg._streaming_active = True
    msg._render_markdown = False
    body = MagicMock()
    msg._body = body

    await msg.stop_stream()

    assert not msg._streaming_active
    body.update.assert_called_once_with("Hello world")


@pytest.mark.asyncio
async def test_stop_stream_renders_ansi_when_render_ansi_enabled() -> None:
    """stop_stream() parses ANSI escapes when render_ansi is True."""
    from rich.text import Text

    msg = AssistantMessage(id="asst-test", render_markdown=False, render_ansi=True)
    msg._content = "\x1b[31mred\x1b[0m"
    msg._streaming_active = True
    body = MagicMock()
    msg._body = body

    await msg.stop_stream()

    body.update.assert_called_once()
    rendered = body.update.call_args[0][0]
    assert isinstance(rendered, Text)
    assert rendered.plain == "red"
    assert rendered.spans


@pytest.mark.asyncio
async def test_stop_stream_no_op_when_content_empty() -> None:
    """stop_stream() renders empty string when content is empty."""
    msg = AssistantMessage(id="asst-test")
    msg._content = ""
    msg._streaming_active = False
    msg._render_markdown = True
    body = MagicMock()
    msg._body = body

    await msg.stop_stream()

    body.update.assert_called_once_with("")


@pytest.mark.asyncio
async def test_set_content_hydration_uses_themed_markdown() -> None:
    """set_content() (used by hydration) renders content with markdown theme.

    Content is set before stop_stream so only one render occurs (no double render).
    """
    msg = AssistantMessage(id="asst-test")
    msg._render_markdown = True
    msg._streaming_active = False
    body = MagicMock()
    msg._body = body

    await msg.set_content("# Hydrated\n\nContent here")

    assert msg._content == "# Hydrated\n\nContent here"
    body.update.assert_called_once()
    call_arg = body.update.call_args[0][0]
    assert isinstance(call_arg, ThemedMarkdownRenderer)


@pytest.mark.asyncio
async def test_flush_does_not_replace_streamed_markdown_with_repaired_text() -> None:
    from soothe_cli.runtime.presentation.renderer_base import RendererBase
    from soothe_cli.tui.textual_adapter import _flush_assistant_text_ns

    raw = "```python\ndef foo3():\n    pass\n```"
    repaired = RendererBase.repair_concatenated_output(raw)
    assert repaired != raw

    msg = AssistantMessage(id="asst-test")
    msg.set_content = AsyncMock()  # type: ignore[method-assign]
    msg.stop_stream = AsyncMock()  # type: ignore[method-assign]
    msg._content = raw

    adapter = MagicMock()
    adapter._sync_message_content = MagicMock()

    await _flush_assistant_text_ns(
        adapter,
        raw,
        (),
        {(): msg},
    )

    msg.stop_stream.assert_awaited_once()
    msg.set_content.assert_not_awaited()
    assert msg._content == repaired


def test_assistant_message_uses_inline_card_dot_row() -> None:
    """AssistantMessage keeps the status dot on the same row as report body text."""
    css = AssistantMessage.DEFAULT_CSS
    assert ".assistant-row" in css
    assert ".assistant-dot" in css
    assert ".assistant-body" in css


def test_selectable_markdown_body_render_line_annotates_offset_meta() -> None:
    """`render_line` must add `offset` style meta to each segment."""
    from rich.segment import Segment
    from textual.strip import Strip

    body = _SelectableMarkdownBody("", markup=False)
    raw = Strip([Segment("Hello world")])
    body._render_cache = type(body._render_cache)(body._render_cache.size, [raw])

    annotated = raw.apply_offsets(0, 0)
    segments_with_offset = [
        seg
        for seg in annotated
        if seg.style is not None and seg.style._meta is not None and "offset" in seg.style.meta
    ]
    assert segments_with_offset, "every segment must carry an `offset` meta after apply_offsets"


def test_selectable_markdown_body_extracts_text_from_render_cache() -> None:
    """`_SelectableMarkdownBody.get_selection` returns visible text for themed markdown."""
    from rich.segment import Segment
    from textual.selection import Selection
    from textual.strip import Strip

    body = _SelectableMarkdownBody("", markup=False)
    body._render_cache = type(body._render_cache)(
        body._render_cache.size,
        [Strip([Segment("Result")]), Strip([Segment("Hello world")])],
    )

    result = body.get_selection(Selection(None, None))

    assert result is not None
    text, ending = result
    assert "Result" in text
    assert "Hello world" in text
    assert ending == "\n"


# ---------------------------------------------------------------------------
# Two-phase rendering (A): plain text while streaming, markdown on stop
# ---------------------------------------------------------------------------


def test_render_to_body_plain_text_while_streaming() -> None:
    """While streaming, the body shows plain text, not a ThemedMarkdownRenderer."""
    msg = AssistantMessage(id="asst-stream")
    msg._content = "# Hello\n\nSome **bold** text"
    msg._streaming_active = True
    msg._render_markdown = True
    body = MagicMock()
    msg._body = body

    msg._render_to_body()

    body.update.assert_called_once_with("# Hello\n\nSome **bold** text")
    call_arg = body.update.call_args[0][0]
    assert not isinstance(call_arg, ThemedMarkdownRenderer)


def test_render_to_body_markdown_when_not_streaming() -> None:
    """When not streaming, the body renders ThemedMarkdownRenderer."""
    msg = AssistantMessage(id="asst-done")
    msg._content = "# Hello\n\nSome text"
    msg._streaming_active = False
    msg._render_markdown = True
    body = MagicMock()
    msg._body = body

    msg._render_to_body()

    body.update.assert_called_once()
    call_arg = body.update.call_args[0][0]
    assert isinstance(call_arg, ThemedMarkdownRenderer)


@pytest.mark.asyncio
async def test_flush_during_stream_renders_plain_text() -> None:
    """_flush_pending_content during active streaming renders plain text."""
    msg = AssistantMessage(id="asst-stream")
    msg._content = "Hello world"
    msg._pending_buffer = " world"
    msg._streaming_active = True
    msg._render_markdown = True
    body = MagicMock()
    msg._body = body

    await msg._flush_pending_content()

    assert msg._pending_buffer == ""
    body.update.assert_called_once_with("Hello world")
    call_arg = body.update.call_args[0][0]
    assert not isinstance(call_arg, ThemedMarkdownRenderer)


@pytest.mark.asyncio
async def test_stop_stream_switches_from_plain_to_markdown() -> None:
    """stop_stream transitions from plain-text streaming to a single markdown render."""
    msg = AssistantMessage(id="asst-transition")
    msg._content = "# Title\n\nParagraph"
    msg._streaming_active = True
    msg._render_markdown = True
    body = MagicMock()
    msg._body = body

    await msg.stop_stream()

    assert not msg._streaming_active
    # Only one render call (the final markdown), no intermediate plain-text flush.
    body.update.assert_called_once()
    call_arg = body.update.call_args[0][0]
    assert isinstance(call_arg, ThemedMarkdownRenderer)


# ---------------------------------------------------------------------------
# Theme caching (B): resolve_markdown_theme_parts called once per widget
# ---------------------------------------------------------------------------


def test_theme_parts_cached_after_first_resolve() -> None:
    """_get_theme_parts resolves once and reuses the cached tuple."""
    msg = AssistantMessage(id="asst-cache")
    msg._render_markdown = True

    parts_a = msg._get_theme_parts()
    parts_b = msg._get_theme_parts()

    assert parts_a is parts_b
    assert msg._cached_theme_parts is not None


def test_render_to_body_uses_cached_theme_parts() -> None:
    """Multiple non-streaming renders reuse the same theme parts (no re-resolve)."""
    msg = AssistantMessage(id="asst-cache2")
    msg._render_markdown = True
    msg._streaming_active = False
    msg._content = "# Title"
    body = MagicMock()
    msg._body = body

    msg._render_to_body()
    cached = msg._cached_theme_parts
    assert cached is not None

    msg._content = "Different content"
    msg._render_to_body()
    assert msg._cached_theme_parts is cached  # still the same tuple


# ---------------------------------------------------------------------------
# Adaptive flush interval (C): fast for first tokens, normal after
# ---------------------------------------------------------------------------


def test_adaptive_flush_interval_fast_for_short_content() -> None:
    """Short content (< 500 chars) uses the fast first-flush interval."""
    msg = AssistantMessage(id="asst-adaptive")
    msg._content = "Hello"
    msg._first_flush_interval = 0.05
    msg._stream_flush_interval = 0.2

    assert msg._adaptive_flush_interval() == 0.05


def test_adaptive_flush_interval_normal_for_long_content() -> None:
    """Long content (>= 500 chars) uses the normal flush interval."""
    msg = AssistantMessage(id="asst-adaptive2")
    msg._content = "x" * 500
    msg._first_flush_interval = 0.05
    msg._stream_flush_interval = 0.2

    assert msg._adaptive_flush_interval() == 0.2


def test_adaptive_flush_interval_boundary() -> None:
    """Exactly at the threshold (499 vs 500 chars) the interval switches."""
    msg = AssistantMessage(id="asst-boundary")
    msg._first_flush_interval = 0.05
    msg._stream_flush_interval = 0.2

    msg._content = "x" * 499
    assert msg._adaptive_flush_interval() == 0.05

    msg._content = "x" * 500
    assert msg._adaptive_flush_interval() == 0.2
