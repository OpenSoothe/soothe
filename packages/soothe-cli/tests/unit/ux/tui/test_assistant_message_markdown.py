"""Tests for AssistantMessage markdown rendering and flush behavior."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from soothe_cli.tui.widgets.messages import AssistantMessage


@pytest.mark.asyncio
async def test_stop_stream_renders_content_to_body() -> None:
    """stop_stream() renders final content via _render_to_body."""
    msg = AssistantMessage(id="asst-test")
    msg._content = "```python\nprint('hello')\n```"
    msg._streaming_active = True
    msg._render_markdown = True
    body = MagicMock()
    msg._body = body

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
