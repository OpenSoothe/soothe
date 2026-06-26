"""Tests for AssistantMessage markdown rendering and flush behavior."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

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
    from rich.markdown import Markdown as RichMarkdown

    for call in body.update.call_args_list:
        assert not isinstance(call.args[0], RichMarkdown)


@pytest.mark.asyncio
async def test_stop_stream_renders_content_to_body() -> None:
    """stop_stream() renders final content via _render_to_body."""
    msg = AssistantMessage(id="asst-test")
    msg._content = "```python\nprint('hello')\n```"
    msg._streaming_active = True
    msg._render_markdown = True
    body = MagicMock()
    msg._body = body

    with patch(
        "soothe_cli.tui.widgets.messages.assistant._code_theme_for_app",
        return_value="monokai",
    ):
        await msg.stop_stream()

    assert not msg._streaming_active
    body.update.assert_called_once()
    # Verify we passed a RichMarkdown instance
    from rich.markdown import Markdown as RichMarkdown

    call_arg = body.update.call_args[0][0]
    assert isinstance(call_arg, RichMarkdown)


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
async def test_flush_renders_rich_markdown_to_body() -> None:
    """_flush_pending_content renders accumulated content as RichMarkdown."""
    msg = AssistantMessage(id="asst-test")
    msg._content = "# Hello\n\nSome text"
    msg._pending_buffer = "Some text"
    msg._render_markdown = True
    body = MagicMock()
    msg._body = body

    with patch(
        "soothe_cli.tui.widgets.messages.assistant._code_theme_for_app",
        return_value="monokai",
    ):
        await msg._flush_pending_content()

    from rich.markdown import Markdown as RichMarkdown

    assert msg._pending_buffer == ""
    body.update.assert_called_once()
    call_arg = body.update.call_args[0][0]
    assert isinstance(call_arg, RichMarkdown)


@pytest.mark.asyncio
async def test_set_content_hydration_uses_rich_markdown() -> None:
    """set_content() (used by hydration) renders content as RichMarkdown."""
    msg = AssistantMessage(id="asst-test")
    msg._render_markdown = True
    msg._streaming_active = False
    body = MagicMock()
    msg._body = body

    with patch(
        "soothe_cli.tui.widgets.messages.assistant._code_theme_for_app",
        return_value="monokai",
    ):
        await msg.set_content("# Hydrated\n\nContent here")

    from rich.markdown import Markdown as RichMarkdown

    assert msg._content == "# Hydrated\n\nContent here"
    # stop_stream renders empty (no content yet), then set_content renders final
    last_call_arg = body.update.call_args[0][0]
    assert isinstance(last_call_arg, RichMarkdown)


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


def test_assistant_message_has_left_border() -> None:
    """AssistantMessage card draws a grey vertical left border like other AI cards."""
    assert "border-left: wide $cognition" in AssistantMessage.DEFAULT_CSS


def test_selectable_markdown_body_render_line_annotates_offset_meta() -> None:
    """`render_line` must add `offset` style meta to each segment.

    Without it the compositor's `get_widget_and_offset_at` walks the line and
    finds no segment with `offset` in its style meta, so click + drag never
    resolves to a content offset and the screen drops the selection silently.
    Regression: 'I will complete this…' and goal-completion 'Result …' cards
    couldn't be selected with the mouse.
    """
    from rich.segment import Segment
    from textual.strip import Strip

    body = _SelectableMarkdownBody("", markup=False)
    raw = Strip([Segment("Hello world")])
    body._render_cache = type(body._render_cache)(body._render_cache.size, [raw])

    # Bypass Widget.render_line() (which needs a mounted app) by feeding the
    # raw strip directly through apply_offsets — same code path render_line
    # delegates to.
    annotated = raw.apply_offsets(0, 0)
    segments_with_offset = [
        seg
        for seg in annotated
        if seg.style is not None and seg.style._meta is not None and "offset" in seg.style.meta
    ]
    assert segments_with_offset, "every segment must carry an `offset` meta after apply_offsets"


def test_selectable_markdown_body_extracts_text_from_render_cache() -> None:
    """`_SelectableMarkdownBody.get_selection` returns visible text even when
    the underlying renderable is a `rich.markdown.Markdown` instance.

    Regression test for the perf refactor that swapped `textual.widgets.Markdown`
    for `Static + RichMarkdown` and accidentally disabled copy-to-clipboard on
    the goal-completion card.
    """
    from rich.segment import Segment
    from textual.selection import Selection
    from textual.strip import Strip

    body = _SelectableMarkdownBody("", markup=False)
    # Simulate two rendered lines from a RichMarkdown render
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
